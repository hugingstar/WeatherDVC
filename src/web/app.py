import os
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, Query, Request, Response, Depends, Cookie
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config import config, get_enabled_locations, get_storage_paths, ROOT_DIR
from src.db import (
    init_db, get_latest_weather, get_recent_history, 
    get_total_record_count, create_user, authenticate_user, 
    get_user_by_username
)
from src.collector import run_collector_loop, collect_all_locations_async
from src.scheduler import start_scheduler, run_dvc_pipeline, get_scheduler_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s")
logger = logging.getLogger("weather.web")
KST = timezone(timedelta(hours=9))

app = FastAPI(
    title="까치는 목욕중 - 실시간 기상 데이터 파이프라인 & DVC 무중단 버전 관리",
    version="2.0.0"
)

# Mount static and templates
static_dir = ROOT_DIR / "src" / "web" / "static"
templates_dir = ROOT_DIR / "src" / "web" / "templates"

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))

# Schemas for Auth
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=4, max_length=100)
    phone: str = Field(..., min_length=8, max_length=30)

class LoginRequest(BaseModel):
    username: str
    password: str

@app.on_event("startup")
async def on_startup():
    logger.info("Initializing DB, Background Scheduler, and 1-minute Collector...")
    init_db()
    # Start scheduler
    start_scheduler()
    # Run collector in background task
    asyncio.create_task(run_collector_loop())
    logger.info("FastAPI Web server, Background Scheduler, and 1-minute Collector started.")

# ----------------- Web UI Routes -----------------
@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    locations = get_enabled_locations()
    
    # Region group mapping for clean tabbed UI
    region_groups = [
        {"id": "all", "name": "전체 관측소"},
        {"id": "capital", "name": "수도권/인천/도서"},
        {"id": "gangwon_west", "name": "강원 영서"},
        {"id": "gangwon_east", "name": "강원 영동"},
        {"id": "gangwon_mountain", "name": "강원 산간"},
        {"id": "chungcheong", "name": "충청/대전/세종"},
        {"id": "jeonbuk", "name": "전북특별자치도"},
        {"id": "honam", "name": "광주/전남/신재생"},
        {"id": "gyeongbuk", "name": "대구/경북/동해안"},
        {"id": "gyeongnam", "name": "부울경/경남"},
        {"id": "jeju", "name": "제주특별자치도"}
    ]
    
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "locations": locations,
            "region_groups": region_groups,
            "app_title": "까치는 목욕중"
        }
    )

# ----------------- Auth API Routes -----------------
@app.post("/api/auth/register")
async def api_register(req: RegisterRequest, response: Response):
    existing = get_user_by_username(req.username)
    if existing:
        raise HTTPException(status_code=400, detail="이미 존재하는 아이디입니다.")
    try:
        user = create_user(req.username, req.password, req.phone)
        response.set_cookie(key="auth_user", value=user["username"], max_age=86400*30, httponly=False)
        return {"status": "success", "message": "회원가입이 완료되었습니다.", "user": {"username": user["username"], "phone": user["phone"]}}
    except Exception as e:
        logger.error(f"Registration failed: {e}")
        raise HTTPException(status_code=500, detail="회원가입 처리 중 오류가 발생했습니다.")

@app.post("/api/auth/login")
async def api_login(req: LoginRequest, response: Response):
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    response.set_cookie(key="auth_user", value=user["username"], max_age=86400*30, httponly=False)
    return {"status": "success", "message": "로그인되었습니다.", "user": {"username": user["username"], "phone": user["phone"]}}

@app.get("/api/auth/me")
async def api_get_current_user(auth_user: Optional[str] = Cookie(None)):
    if not auth_user:
        return {"status": "unauthenticated"}
    user = get_user_by_username(auth_user)
    if user:
        return {"status": "authenticated", "user": {"username": user["username"], "phone": user["phone"]}}
    return {"status": "unauthenticated"}

@app.post("/api/auth/logout")
async def api_logout(response: Response):
    response.delete_cookie(key="auth_user")
    return {"status": "success", "message": "로그아웃되었습니다."}

# ----------------- Weather Data API Routes -----------------
@app.get("/api/weather/latest")
async def api_get_latest_weather():
    records = get_latest_weather()
    return {"status": "success", "count": len(records), "data": records}

@app.get("/api/weather/history")
async def api_get_history(
    location_id: Optional[str] = Query("all", description="Location ID or 'all'"),
    limit: int = Query(100, ge=1, le=1000)
):
    records = get_recent_history(location_id=location_id, limit=limit)
    return {"status": "success", "count": len(records), "data": records}

@app.get("/api/locations")
async def api_get_locations():
    return {"status": "success", "data": get_enabled_locations()}

@app.get("/api/status")
async def api_get_status():
    total_records = get_total_record_count()
    sched_status = get_scheduler_status()
    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "status": "success",
        "current_time_kst": now_kst,
        "total_records": total_records,
        "interval_seconds": config["collection"].get("interval_seconds", 60),
        "scheduler": sched_status,
        "locations_count": len(get_enabled_locations())
    }

@app.post("/api/collector/trigger")
async def api_trigger_collect():
    records = await collect_all_locations_async()
    return {"status": "success", "collected_count": len(records), "timestamp": datetime.now(KST).isoformat()}

@app.post("/api/pipeline/trigger")
async def api_trigger_pipeline(date: Optional[str] = None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_dvc_pipeline, date)
    return {"status": "success", "result": result}

@app.get("/api/reports")
async def api_list_reports():
    paths = get_storage_paths()
    reports_dir = paths["reports"]
    reports = []
    if reports_dir.exists():
        for file in sorted(reports_dir.glob("*.html"), key=os.path.getmtime, reverse=True):
            if file.name != "latest.html":
                reports.append({
                    "filename": file.name,
                    "size_bytes": file.stat().st_size,
                    "modified_at": datetime.fromtimestamp(file.stat().st_mtime, tz=KST).strftime("%Y-%m-%d %H:%M:%S"),
                    "url": f"/reports/{file.name}"
                })
    return {"status": "success", "reports": reports}

@app.get("/reports/{report_name}")
async def view_report(report_name: str):
    paths = get_storage_paths()
    file_path = paths["reports"] / report_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(file_path, media_type="text/html")

@app.get("/api/metrics")
async def api_get_quality_metrics():
    paths = get_storage_paths()
    metrics_file = paths["metrics"] / "quality_summary.json"
    if metrics_file.exists():
        with open(metrics_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"status": "success", "metrics": data}
    return {"status": "not_found", "message": "No quality metrics available yet."}
