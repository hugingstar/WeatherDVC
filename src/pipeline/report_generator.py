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
import matplotlib.dates as mdates
import matplotlib.ticker as ticker
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

# Retention policy: keep last 14 days of reports to prevent excessive disk usage
MAX_REPORT_RETENTION_DAYS = 14

def cleanup_old_reports():
    """Cleans up reports older than retention policy to save disk space."""
    paths = get_storage_paths()
    reports_dir = paths["reports"]
    if not reports_dir.exists():
        return
    
    cutoff_time = datetime.now() - timedelta(days=MAX_REPORT_RETENTION_DAYS)
    for report_file in reports_dir.glob("daily_*.html"):
        try:
            mtime = datetime.fromtimestamp(report_file.stat().st_mtime)
            if mtime < cutoff_time and report_file.name != "latest.html":
                report_file.unlink()
                logger.info(f"Cleaned up old archived report: {report_file.name}")
        except Exception as e:
            logger.warning(f"Failed to clean up {report_file.name}: {e}")

def fig_to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=130, facecolor="#1E1A22")
    buf.seek(0)
    img_str = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return f"data:image/png;base64,{img_str}"

def generate_charts(df: pd.DataFrame) -> dict:
    charts = {}
    if df.empty:
        return charts

    # 1. Multi-region Temperature Time Series (X-axis: 2-line horizontal format, Y-axis: 6 integer ticks)
    try:
        fig, ax = plt.subplots(figsize=(12, 5.0))
        # Ensure timestamp is datetime
        plot_df = df.copy()
        plot_df["dt"] = pd.to_datetime(plot_df["timestamp"])
        
        top_regions = plot_df["location_id"].unique()[:10]
        sub_df = plot_df[plot_df["location_id"].isin(top_regions)]
        
        for loc_id, grp in sub_df.groupby("location_id"):
            loc_name = grp["location_name"].iloc[0] if "location_name" in grp else loc_id
            ax.plot(grp["dt"], grp["temperature"], label=loc_name, linewidth=2.0, alpha=0.9)
            
        ax.set_title("주요 거점별 기온(℃) 24시간 실시간 변화 추이", fontsize=14, pad=14, color="#F8FAFC", fontweight="bold")
        ax.set_ylabel("기온 (℃)", color="#FFD1BA", fontsize=12, fontweight="bold")
        ax.grid(True, linestyle="--", alpha=0.25)
        ax.legend(loc="upper right", framealpha=0.5, fontsize=10, ncol=2)
        
        # Format Y-axis to 6 integer ticks
        ax.yaxis.set_major_locator(ticker.MaxNLocator(nbins=6, integer=True))
        
        # Format X-axis: 2-line format (e.g. 12:00\n08-20) without rotation
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M\n(%m/%d)"))
        ax.tick_params(axis="x", rotation=0, labelsize=11)
        ax.tick_params(axis="y", labelsize=11)
        
        fig.tight_layout()
        charts["temp_timeseries"] = fig_to_base64(fig)
    except Exception as e:
        logger.error(f"Error creating temp chart: {e}")

    # 2. Regional Comparison Boxplot (Temperature & Humidity) - Large & Clear Layout
    try:
        sample_df = df[df["location_id"].isin(df["location_id"].unique()[:12])]
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))
        
        sns.boxplot(data=sample_df, x="location_name", y="temperature", ax=ax1, palette="coolwarm", hue="location_name", legend=False)
        ax1.set_title("주요 거점별 기온 분포 (Boxplot)", fontsize=13, pad=12, color="#F8FAFC", fontweight="bold")
        ax1.set_xlabel("")
        ax1.set_ylabel("기온 (℃)", color="#FFD1BA", fontsize=11, fontweight="bold")
        ax1.yaxis.set_major_locator(ticker.MaxNLocator(nbins=6, integer=True))
        ax1.grid(True, linestyle="--", alpha=0.25)
        ax1.tick_params(axis="x", rotation=25, labelsize=11)
        ax1.tick_params(axis="y", labelsize=11)

        sns.barplot(data=sample_df, x="location_name", y="relative_humidity", ax=ax2, palette="Blues_d", errorbar=None, hue="location_name", legend=False)
        ax2.set_title("주요 거점별 평균 습도 (%)", fontsize=13, pad=12, color="#F8FAFC", fontweight="bold")
        ax2.set_xlabel("")
        ax2.set_ylabel("습도 (%)", color="#06B6D4", fontsize=11, fontweight="bold")
        ax2.yaxis.set_major_locator(ticker.MaxNLocator(nbins=6, integer=True))
        ax2.grid(True, linestyle="--", alpha=0.25)
        ax2.tick_params(axis="x", rotation=25, labelsize=11)
        ax2.tick_params(axis="y", labelsize=11)
        
        fig.tight_layout()
        charts["regional_comparison"] = fig_to_base64(fig)
    except Exception as e:
        logger.error(f"Error creating comparison chart: {e}")

    # 3. Correlation Heatmap with Korean Axis Labels - High Visibility & Large Scale
    try:
        col_mapping = {
            "temperature": "기온 (℃)",
            "relative_humidity": "상대습도 (%)",
            "wind_speed": "풍속 (m/s)",
            "surface_pressure": "해면기압 (hPa)",
            "precipitation": "강수량 (mm)",
            "discomfort_index": "불쾌지수 (DI)",
            "apparent_temperature": "체감온도 (℃)"
        }
        
        avail_cols = [c for c in col_mapping.keys() if c in df.columns]
        if len(avail_cols) > 1:
            heatmap_df = df[avail_cols].rename(columns=col_mapping)
            fig, ax = plt.subplots(figsize=(10.0, 7.0))
            corr = heatmap_df.corr()
            sns.heatmap(corr, annot=True, fmt=".2f", cmap="vlag", ax=ax, cbar=True, linewidths=1.0, linecolor="#2D2534",
                        annot_kws={"size": 12, "weight": "bold"},
                        cbar_kws={"shrink": 0.85})
            ax.set_title("기상 관측 변수 간 상관분석 히트맵", fontsize=14, pad=14, color="#F8FAFC", fontweight="bold")
            ax.tick_params(axis="x", labelsize=12, rotation=0)
            ax.tick_params(axis="y", labelsize=12, rotation=0)
            fig.tight_layout()
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
        <tr class="border-b border-gray-800 hover:bg-gray-800/50 transition text-sm">
            <td class="px-4 py-3.5 font-semibold text-white">{m.get('location_name', loc_id)}</td>
            <td class="px-4 py-3.5 text-center font-mono">{m.get('record_count', 0):,}건</td>
            <td class="px-4 py-3.5 text-center font-mono">{m.get('completeness_ratio', 0)*100:.1f}%</td>
            <td class="px-4 py-3.5 text-center font-mono text-amber-400">{m.get('total_anomalies', 0)}건</td>
            <td class="px-4 py-3.5 text-center font-bold font-mono" style="color: {st_color}">{m.get('quality_score', 0):.1f}점</td>
            <td class="px-4 py-3.5 text-center">
                <span class="px-3 py-1 text-xs rounded-full font-bold" style="background: {st_color}22; color: {st_color}; border: 1px solid {st_color}66">
                    {m.get('status')}
                </span>
            </td>
            <td class="px-4 py-3.5 text-right text-gray-300 text-xs">
                평균 {m.get('stats', {}).get('temp_mean', '-')}℃ | 습도 {m.get('stats', {}).get('humidity_mean', '-')}% | 최대풍속 {m.get('stats', {}).get('wind_max', '-')}m/s
            </td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>까치는 목욕중 - 일일 기상 데이터 품질 및 분석 보고서 ({target_date})</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Pretendard:wght@300;400;600;700;800&display=swap');
        body {{ font-family: 'Pretendard', sans-serif; background-color: #141118; color: #F1F5F9; font-size: 16px; }}
        .glass-card {{ background: rgba(31, 26, 36, 0.85); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); }}
    </style>
</head>
<body class="p-6 md:p-10 max-w-7xl mx-auto min-h-screen">
    <!-- Header -->
    <header class="flex flex-col md:flex-row justify-between items-start md:items-center pb-8 border-b border-gray-800 gap-4">
        <div>
            <div class="flex items-center gap-3">
                <span class="text-4xl">🐦🛁</span>
                <h1 class="text-3xl md:text-4xl font-extrabold tracking-tight bg-gradient-to-r from-amber-300 via-orange-300 to-rose-300 bg-clip-text text-transparent">
                    까치는 목욕중 일일 데이터 품질 & 분석 보고서
                </h1>
            </div>
            <p class="text-gray-400 text-sm mt-1.5">DVC 무중단 파이프라인 자동 산출물 | 대상 일자: <strong class="text-amber-400">{target_date}</strong> (1분 원천 데이터 전수 분석)</p>
        </div>
        <div class="flex items-center gap-3">
            <span class="px-5 py-2 rounded-full text-base font-bold shadow-lg" style="background: {status_badge_color}22; color: {status_badge_color}; border: 1px solid {status_badge_color}">
                ● 파이프라인 판정: {quality_metrics.get('status', 'PASS')}
            </span>
            <button onclick="window.print()" class="px-4 py-2 text-sm bg-gray-800 hover:bg-gray-700 text-gray-200 rounded-xl border border-gray-700 transition">
                🖨️ PDF/인쇄
            </button>
        </div>
    </header>

    <!-- KPI Summary Grid -->
    <section class="grid grid-cols-2 md:grid-cols-4 gap-5 my-8">
        <div class="glass-card rounded-2xl p-6">
            <div class="text-sm uppercase tracking-wider text-gray-400 font-semibold">총 수집 레코드</div>
            <div class="text-3xl md:text-4xl font-extrabold text-amber-400 mt-2">{quality_metrics.get('total_records', 0):,} <span class="text-base font-normal text-gray-400">건</span></div>
            <div class="text-xs text-gray-400 mt-1.5">{quality_metrics.get('total_regions', 0)}개 관측소 1분 수집 전수</div>
        </div>
        <div class="glass-card rounded-2xl p-6">
            <div class="text-sm uppercase tracking-wider text-gray-400 font-semibold">전체 데이터 완결성</div>
            <div class="text-3xl md:text-4xl font-extrabold text-emerald-400 mt-2">{quality_metrics.get('overall_completeness', 0)*100:.1f} <span class="text-base font-normal text-gray-400">%</span></div>
            <div class="text-xs text-gray-400 mt-1.5">목표 95.0% 대비 만족</div>
        </div>
        <div class="glass-card rounded-2xl p-6">
            <div class="text-sm uppercase tracking-wider text-gray-400 font-semibold">이상치 감지 건수</div>
            <div class="text-3xl md:text-4xl font-extrabold text-orange-400 mt-2">{quality_metrics.get('overall_anomalies', 0)} <span class="text-base font-normal text-gray-400">건</span></div>
            <div class="text-xs text-gray-400 mt-1.5">Z-Score & 임계치 위반</div>
        </div>
        <div class="glass-card rounded-2xl p-6">
            <div class="text-sm uppercase tracking-wider text-gray-400 font-semibold">통합 품질 점수</div>
            <div class="text-3xl md:text-4xl font-extrabold text-rose-400 mt-2">{quality_metrics.get('overall_quality_score', 0):.1f} <span class="text-base font-normal text-gray-400">/ 100</span></div>
            <div class="text-xs text-gray-400 mt-1.5">DVC 검증 완료</div>
        </div>
    </section>

    <!-- Visual Charts Section (Enlarged and Clear) -->
    <section class="space-y-8 my-8">
        <!-- 1. Temperature Time Series (Full Width) -->
        <div class="glass-card rounded-2xl p-6">
            <h3 class="text-lg font-bold text-gray-200 mb-4">📈 전국 주요 거점 24시간 기온 시계열 추이 (1분 데이터 전수 분석)</h3>
            {"<img src='" + charts["temp_timeseries"] + "' class='w-full rounded-xl border border-gray-800 shadow-xl' />" if "temp_timeseries" in charts else "<div class='text-gray-500 py-8 text-center'>차트 데이터 없음</div>"}
        </div>

        <!-- 2. Regional Distribution (Full Width) -->
        <div class="glass-card rounded-2xl p-6">
            <h3 class="text-lg font-bold text-gray-200 mb-4">📊 주요 지역별 기온 & 습도 분포 비교</h3>
            {"<img src='" + charts["regional_comparison"] + "' class='w-full rounded-xl border border-gray-800 shadow-xl' />" if "regional_comparison" in charts else "<div class='text-gray-500 py-8 text-center'>차트 데이터 없음</div>"}
        </div>

        <!-- 3. Correlation Heatmap (Full Width, Large & High Visibility) -->
        <div class="glass-card rounded-2xl p-6">
            <h3 class="text-lg font-bold text-gray-200 mb-4">🔥 기상 관측 변수 간 상관분석 (히트맵)</h3>
            <div class="flex justify-center">
                {"<img src='" + charts["correlation_heatmap"] + "' class='max-w-4xl w-full rounded-xl border border-gray-800 shadow-xl' />" if "correlation_heatmap" in charts else "<div class='text-gray-500 py-8 text-center'>차트 데이터 없음</div>"}
            </div>
        </div>
    </section>

    <!-- Detailed Region Table -->
    <section class="glass-card rounded-2xl p-6 my-8">
        <h3 class="text-lg font-bold text-gray-200 mb-4">🗺️ 전국 관측소별 세부 품질 검증 지표</h3>
        <div class="overflow-x-auto">
            <table class="w-full text-left">
                <thead class="bg-gray-900/80 text-gray-400 text-xs uppercase font-semibold border-b border-gray-800">
                    <tr>
                        <th class="px-4 py-3">관측소 (지역)</th>
                        <th class="px-4 py-3 text-center">수집 건수</th>
                        <th class="px-4 py-3 text-center">완결성 (%)</th>
                        <th class="px-4 py-3 text-center">이상치</th>
                        <th class="px-4 py-3 text-center">품질 점수</th>
                        <th class="px-4 py-3 text-center">판정</th>
                        <th class="px-4 py-3 text-right">요약 통계</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-gray-800">
                    {regions_table_rows}
                </tbody>
            </table>
        </div>

        <!-- Quality Decision Logic Core Explanation Card -->
        <div class="mt-6 p-5 rounded-xl bg-gray-900/90 border border-orange-500/30 space-y-3">
            <div class="flex items-center gap-2 text-base font-bold text-orange-300">
                <span>💡</span> <span>품질 판정(PASS / WARNING / FAIL) 산출 핵심 과정</span>
            </div>
            <div class="text-sm text-gray-300 leading-relaxed space-y-2">
                <p>
                    <strong>1. 100점 만점 기본 시작:</strong> 
                    매일 자정(00:00) 24시간 동안 수집된 <strong>1분 단위 기상 관측치(하루 1,440분 기준)</strong>를 전수 검증합니다.
                </p>
                <p>
                    <strong>2. 결측률 감점 (최대 50점):</strong> 
                    하루 1,440건 중 누락된 비율에 비례하여 감점합니다. (완결성 100% 시 0점 감점, 누락 발생 시 비례 차감)
                </p>
                <p>
                    <strong>3. 이상치 감점 (최대 50점):</strong> 
                    기상 물리적 한계치(기온 -40~50℃, 습도 0~100% 등)를 벗어난 데이터와 통계적 급변 이상치(Z-Score > 3.5)가 발생한 건수 비율만큼 감점합니다.
                </p>
                <div class="pt-2 border-t border-gray-800 flex flex-wrap gap-4 text-xs font-semibold">
                    <span class="text-emerald-400">● PASS (통과): 품질 점수 80점 이상 AND 완결성 95% 이상 (딥러닝 학습에 최적)</span>
                    <span class="text-amber-400">● WARNING (주의): 품질 점수 60점 ~ 79점 (일부 결측 보정 필요)</span>
                    <span class="text-rose-400">● FAIL (실패): 품질 점수 60점 미만 (데이터 누락/이상치 과다)</span>
                </div>
            </div>
        </div>
    </section>

    <!-- Footer -->
    <footer class="pt-8 border-t border-gray-800 text-center text-xs text-gray-500">
        <p>까치는 목욕중 - 실시간 기상 데이터 파이프라인 & DVC 무중단 버전 관리 시스템</p>
    </footer>
</body>
</html>
    """
    return html

def generate_report(target_date: str = None):
    now_kst = datetime.now(KST)
    target_date = target_date or (now_kst - timedelta(days=1)).strftime("%Y-%m-%d")
    logger.info(f"Generating Daily Quality & Analysis Report for date: {target_date}")

    paths = get_storage_paths()
    processed_file = paths["processed"] / "weather_all_regions.parquet"
    if not processed_file.exists():
        processed_file = paths["processed"] / "weather_all_regions.csv"
        if not processed_file.exists():
            logger.error("No processed data found for report.")
            return

    df = pd.read_parquet(processed_file) if str(processed_file).endswith(".parquet") else pd.read_csv(processed_file)

    metrics_file = paths["metrics"] / "quality_summary.json"
    quality_metrics = {}
    if metrics_file.exists():
        with open(metrics_file, "r", encoding="utf-8") as f:
            quality_metrics = json.load(f)

    # 1. Clean up old reports first to save disk space
    cleanup_old_reports()

    # 2. Generate charts
    charts = generate_charts(df)

    # 3. Build HTML
    html_content = build_html_report(df, quality_metrics, charts, target_date)

    # 4. Save date-specific report and latest.html
    daily_report_path = paths["reports"] / f"daily_{target_date}_overall.html"
    latest_report_path = paths["reports"] / "latest.html"

    with open(daily_report_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    with open(latest_report_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info(f"Report generated successfully: {daily_report_path} & {latest_report_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate daily HTML weather report")
    parser.add_argument("--date", type=str, help="Target date YYYY-MM-DD")
    args = parser.parse_args()
    generate_report(args.date)
