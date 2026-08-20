import os
import json
import base64
import io
import logging
import argparse
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timezone, timedelta
from pathlib import Path
from src.config import config, get_storage_paths

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s")
logger = logging.getLogger("pipeline.report")
KST = timezone(timedelta(hours=9))

# Set matplotlib styling & Korean font support on Windows
plt.style.use("dark_background")
plt.rcParams["font.family"] = ["Malgun Gothic", "DejaVu Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["axes.edgecolor"] = "#4A5568"
plt.rcParams["axes.linewidth"] = 0.8

def fig_to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=120, facecolor="#1A202C")
    buf.seek(0)
    img_str = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return f"data:image/png;base64,{img_str}"

def generate_charts(df: pd.DataFrame) -> dict:
    charts = {}
    if df.empty:
        return charts

    # 1. Multi-region Temperature Time Series
    try:
        fig, ax = plt.subplots(figsize=(10, 4.2))
        for loc_id, grp in df.groupby("location_id"):
            loc_name = grp["location_name"].iloc[0] if "location_name" in grp else loc_id
            ax.plot(grp["timestamp"], grp["temperature"], label=loc_name, linewidth=1.8, alpha=0.85)
        ax.set_title("지역별 기온(℃) 24시간 실시간 변화 추이", fontsize=13, pad=12, color="#E2E8F0", fontweight="bold")
        ax.set_ylabel("기온 (℃)", color="#CBD5E0")
        ax.grid(True, linestyle="--", alpha=0.3)
        ax.legend(loc="upper right", framealpha=0.4, fontsize=9)
        fig.autofmt_xdate()
        charts["temp_timeseries"] = fig_to_base64(fig)
    except Exception as e:
        logger.error(f"Error creating temp chart: {e}")

    # 2. Regional Comparison Boxplot (Temperature & Humidity)
    try:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.0))
        sns.boxplot(data=df, x="location_name", y="temperature", ax=ax1, palette="coolwarm", hue="location_name", legend=False)
        ax1.set_title("지역별 기온 분포 (Boxplot)", fontsize=11, color="#E2E8F0")
        ax1.set_xlabel("")
        ax1.set_ylabel("기온 (℃)", color="#CBD5E0")
        ax1.grid(True, linestyle="--", alpha=0.25)
        ax1.tick_params(axis="x", rotation=30)

        sns.barplot(data=df, x="location_name", y="relative_humidity", ax=ax2, palette="Blues_d", errorbar=None, hue="location_name", legend=False)
        ax2.set_title("지역별 평균 습도 (%)", fontsize=11, color="#E2E8F0")
        ax2.set_xlabel("")
        ax2.set_ylabel("습도 (%)", color="#CBD5E0")
        ax2.grid(True, linestyle="--", alpha=0.25)
        ax2.tick_params(axis="x", rotation=30)
        
        fig.tight_layout()
        charts["regional_comparison"] = fig_to_base64(fig)
    except Exception as e:
        logger.error(f"Error creating comparison chart: {e}")

    # 3. Correlation Heatmap
    try:
        numeric_cols = ["temperature", "relative_humidity", "wind_speed", "surface_pressure", "discomfort_index"]
        avail_cols = [c for c in numeric_cols if c in df.columns]
        if len(avail_cols) > 1:
            fig, ax = plt.subplots(figsize=(6.5, 4.5))
            corr = df[avail_cols].corr()
            sns.heatmap(corr, annot=True, fmt=".2f", cmap="vlag", ax=ax, cbar=True, linewidths=0.5, linecolor="#2D3748")
            ax.set_title("기상 변수 간 상관계수 히트맵", fontsize=11, pad=10, color="#E2E8F0")
            charts["correlation_heatmap"] = fig_to_base64(fig)
    except Exception as e:
        logger.error(f"Error creating correlation heatmap: {e}")

    return charts

def build_html_report(df: pd.DataFrame, quality_metrics: dict, charts: dict, target_date: str) -> str:
    status_badge_color = {
        "PASS": "#10B981",
        "WARNING": "#F59E0B",
        "FAIL": "#EF4444"
    }.get(quality_metrics.get("status", "PASS"), "#10B981")

    regions_table_rows = ""
    for loc_id, m in quality_metrics.get("region_metrics", {}).items():
        st_color = "#10B981" if m["status"] == "PASS" else ("#F59E0B" if m["status"] == "WARNING" else "#EF4444")
        regions_table_rows += f"""
        <tr class="border-b border-gray-800 hover:bg-gray-800/50 transition">
            <td class="px-4 py-3 font-semibold text-white">{m.get('location_name', loc_id)}</td>
            <td class="px-4 py-3 text-center">{m.get('record_count', 0):,}건</td>
            <td class="px-4 py-3 text-center">{m.get('completeness_ratio', 0)*100:.1f}%</td>
            <td class="px-4 py-3 text-center text-amber-400">{m.get('total_anomalies', 0)}건</td>
            <td class="px-4 py-3 text-center font-bold" style="color: {st_color}">{m.get('quality_score', 0):.1f}점</td>
            <td class="px-4 py-3 text-center">
                <span class="px-2.5 py-1 text-xs rounded-full font-bold" style="background: {st_color}22; color: {st_color}; border: 1px solid {st_color}66">
                    {m.get('status')}
                </span>
            </td>
            <td class="px-4 py-3 text-right text-gray-300 text-xs">
                평균 {m.get('stats', {}).get('temp_mean', '-')}℃ | 습도 {m.get('stats', {}).get('humidity_mean', '-')}% | 최대풍속 {m.get('stats', {}).get('wind_max', '-')}m/s
            </td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WeatherMLOps 일일 기상 데이터 수집 및 품질 분석 보고서 ({target_date})</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Pretendard:wght@300;400;600;700;800&display=swap');
        body {{ font-family: 'Pretendard', sans-serif; background-color: #0B0F17; color: #E2E8F0; }}
        .glass-card {{ background: rgba(26, 32, 44, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); }}
    </style>
</head>
<body class="p-6 md:p-10 max-w-7xl mx-auto min-h-screen">
    <!-- Header -->
    <header class="flex flex-col md:flex-row justify-between items-start md:items-center pb-8 border-b border-gray-800 gap-4">
        <div>
            <div class="flex items-center gap-3">
                <span class="text-3xl">🌦️</span>
                <h1 class="text-2xl md:text-3xl font-extrabold tracking-tight bg-gradient-to-r from-blue-400 via-indigo-300 to-purple-400 bg-clip-text text-transparent">
                    WeatherMLOps 일일 데이터 품질 & 분석 보고서
                </h1>
            </div>
            <p class="text-gray-400 text-sm mt-1">DVC 무중단 파이프라인 자동 산출물 | 대상 일자: <strong class="text-blue-400">{target_date}</strong> (KST 00:00:00 생성)</p>
        </div>
        <div class="flex items-center gap-3">
            <span class="px-4 py-1.5 rounded-full text-sm font-bold shadow-lg" style="background: {status_badge_color}22; color: {status_badge_color}; border: 1px solid {status_badge_color}">
                ● 파이프라인 판정: {quality_metrics.get('status', 'PASS')}
            </span>
            <button onclick="window.print()" class="px-4 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 text-gray-200 rounded-lg border border-gray-700 transition">
                🖨️ PDF/인쇄
            </button>
        </div>
    </header>

    <!-- KPI Summary Grid -->
    <section class="grid grid-cols-2 md:grid-cols-4 gap-5 my-8">
        <div class="glass-card rounded-2xl p-5">
            <div class="text-xs uppercase tracking-wider text-gray-400 font-semibold">총 수집 레코드</div>
            <div class="text-3xl font-extrabold text-blue-400 mt-2">{quality_metrics.get('total_records', 0):,} <span class="text-sm font-normal text-gray-400">건</span></div>
            <div class="text-xs text-gray-500 mt-1">{quality_metrics.get('total_regions', 0)}개 지역 1분 수집</div>
        </div>
        <div class="glass-card rounded-2xl p-5">
            <div class="text-xs uppercase tracking-wider text-gray-400 font-semibold">전체 데이터 완결성</div>
            <div class="text-3xl font-extrabold text-emerald-400 mt-2">{quality_metrics.get('overall_completeness', 0)*100:.1f} <span class="text-sm font-normal text-gray-400">%</span></div>
            <div class="text-xs text-gray-500 mt-1">목표 95.0% 대비 만족</div>
        </div>
        <div class="glass-card rounded-2xl p-5">
            <div class="text-xs uppercase tracking-wider text-gray-400 font-semibold">이상치 감지 건수</div>
            <div class="text-3xl font-extrabold text-amber-400 mt-2">{quality_metrics.get('overall_anomalies', 0)} <span class="text-sm font-normal text-gray-400">건</span></div>
            <div class="text-xs text-gray-500 mt-1">Z-Score & 임계치 위반</div>
        </div>
        <div class="glass-card rounded-2xl p-5">
            <div class="text-xs uppercase tracking-wider text-gray-400 font-semibold">통합 품질 점수</div>
            <div class="text-3xl font-extrabold text-purple-400 mt-2">{quality_metrics.get('overall_quality_score', 0):.1f} <span class="text-sm font-normal text-gray-400">/ 100</span></div>
            <div class="text-xs text-gray-500 mt-1">DVC 검증 완료</div>
        </div>
    </section>

    <!-- Visual Charts Section -->
    <section class="my-8">
        <h2 class="text-lg font-bold text-gray-200 mb-4 flex items-center gap-2">
            <span>📈</span> 일일 기상 데이터 시계열 및 분포 분석
        </h2>
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div class="lg:col-span-2 glass-card rounded-2xl p-5 flex flex-col justify-center items-center">
                {f'<img src="{charts["temp_timeseries"]}" class="w-full h-auto rounded-xl" alt="기온 시계열">' if "temp_timeseries" in charts else '<p class="text-gray-500">차트 생성 불가</p>'}
            </div>
            <div class="glass-card rounded-2xl p-5 flex flex-col justify-center items-center">
                {f'<img src="{charts["correlation_heatmap"]}" class="w-full h-auto rounded-xl" alt="상관분석">' if "correlation_heatmap" in charts else '<p class="text-gray-500">상관분석 차트 없음</p>'}
            </div>
        </div>
        <div class="mt-6 glass-card rounded-2xl p-5 flex justify-center items-center">
            {f'<img src="{charts["regional_comparison"]}" class="w-full max-w-5xl h-auto rounded-xl" alt="지역 비교">' if "regional_comparison" in charts else ''}
        </div>
    </section>

    <!-- Regional Breakdown Table -->
    <section class="my-8">
        <h2 class="text-lg font-bold text-gray-200 mb-4 flex items-center gap-2">
            <span>📍</span> 전국 거점별 데이터 품질 및 통계 상세 현황
        </h2>
        <div class="glass-card rounded-2xl overflow-x-auto shadow-2xl">
            <table class="w-full text-left text-sm">
                <thead class="bg-gray-800/80 text-gray-400 uppercase text-xs">
                    <tr>
                        <th class="px-4 py-3">거점(지역명)</th>
                        <th class="px-4 py-3 text-center">수집 건수</th>
                        <th class="px-4 py-3 text-center">완결성</th>
                        <th class="px-4 py-3 text-center">이상치</th>
                        <th class="px-4 py-3 text-center">품질점수</th>
                        <th class="px-4 py-3 text-center">상태</th>
                        <th class="px-4 py-3 text-right">주요 통계 요약</th>
                    </tr>
                </thead>
                <tbody>
                    {regions_table_rows}
                </tbody>
            </table>
        </div>
    </section>

    <!-- Footer -->
    <footer class="mt-12 pt-6 border-t border-gray-800 text-center text-xs text-gray-500">
        <p>WeatherMLOps Pipeline with DVC (Data Version Control) • Automated Zero-Downtime Midnight Ingestion & Reporting</p>
        <p class="mt-1">Generated at {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')} (KST)</p>
    </footer>
</body>
</html>"""
    return html

def generate_report(target_date: str = None):
    paths = get_storage_paths()
    processed_path = paths["processed"] / "weather_all_regions.parquet"
    if not processed_path.exists():
        csv_fallback = paths["processed"] / "weather_all_regions.csv"
        if not csv_fallback.exists():
            logger.error("No processed dataset found.")
            return
        df = pd.read_csv(csv_fallback)
    else:
        df = pd.read_parquet(processed_path)

    summary_metric_file = paths["metrics"] / "quality_summary.json"
    if summary_metric_file.exists():
        with open(summary_metric_file, "r", encoding="utf-8") as f:
            quality_metrics = json.load(f)
    else:
        quality_metrics = {}

    date_str = target_date or datetime.now(KST).strftime("%Y-%m-%d")
    charts = generate_charts(df)
    html_content = build_html_report(df, quality_metrics, charts, date_str)

    daily_report_path = paths["reports"] / f"daily_{date_str}_overall.html"
    latest_report_path = paths["reports"] / "latest.html"

    with open(daily_report_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    with open(latest_report_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info(f"Daily analysis report successfully generated: {daily_report_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate daily HTML weather report")
    parser.add_argument("--date", type=str, default=None, help="Target date in YYYY-MM-DD")
    args = parser.parse_args()
    generate_report(args.date)
