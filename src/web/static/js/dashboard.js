// WeatherMLOps Dashboard JavaScript Logic
let selectedLocation = "all";
let latestWeatherData = [];
let historyData = [];
let realtimeChart = null;
let comparisonChart = null;
let autoRefreshTimer = null;
let currentTab = "history";

document.addEventListener("DOMContentLoaded", () => {
    initCharts();
    loadDashboardData();
    setupEventListeners();
    
    // Auto refresh every 15 seconds
    autoRefreshTimer = setInterval(() => {
        loadDashboardData(false);
    }, 15000);
});

function setupEventListeners() {
    // Region selection tabs
    document.querySelectorAll(".region-tab-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            document.querySelectorAll(".region-tab-btn").forEach(b => b.classList.remove("active-region"));
            btn.classList.add("active-region");
            selectedLocation = btn.dataset.location;
            updateLocationView();
            loadHistory();
        });
    });

    // Top Action Buttons
    document.getElementById("btn-collect-now")?.addEventListener("click", triggerCollectNow);
    document.getElementById("btn-run-pipeline")?.addEventListener("click", triggerPipelineNow);
    document.getElementById("btn-refresh")?.addEventListener("click", () => loadDashboardData(true));
    document.getElementById("btn-export-csv")?.addEventListener("click", exportHistoryToCSV);
    
    // Table Search
    document.getElementById("history-search")?.addEventListener("input", (e) => {
        filterHistoryTable(e.target.value);
    });

    // Main Content Tabs (History vs Reports)
    document.getElementById("tab-btn-history")?.addEventListener("click", () => switchTab("history"));
    document.getElementById("tab-btn-reports")?.addEventListener("click", () => switchTab("reports"));
}

function switchTab(tab) {
    currentTab = tab;
    if (tab === "history") {
        document.getElementById("tab-btn-history").classList.add("border-blue-500", "text-blue-400");
        document.getElementById("tab-btn-history").classList.remove("border-transparent", "text-gray-400");
        document.getElementById("tab-btn-reports").classList.remove("border-blue-500", "text-blue-400");
        document.getElementById("tab-btn-reports").classList.add("border-transparent", "text-gray-400");
        
        document.getElementById("history-section").classList.remove("hidden");
        document.getElementById("reports-section").classList.add("hidden");
    } else {
        document.getElementById("tab-btn-reports").classList.add("border-blue-500", "text-blue-400");
        document.getElementById("tab-btn-reports").classList.remove("border-transparent", "text-gray-400");
        document.getElementById("tab-btn-history").classList.remove("border-blue-500", "text-blue-400");
        document.getElementById("tab-btn-history").classList.add("border-transparent", "text-gray-400");

        document.getElementById("history-section").classList.add("hidden");
        document.getElementById("reports-section").classList.remove("hidden");
        loadReportsAndMetrics();
    }
}

async function loadDashboardData(showToast = false) {
    try {
        await Promise.all([
            loadStatus(),
            loadLatestWeather(),
            loadHistory(),
            loadQualityMetrics()
        ]);
        if (showToast) showNotification("데이터가 최신 상태로 갱신되었습니다.", "success");
    } catch (err) {
        console.error("Failed to load dashboard data:", err);
    }
}

async function loadStatus() {
    const res = await fetch("/api/status");
    const data = await res.json();
    if (data.status === "success") {
        document.getElementById("stat-total-records").innerText = Number(data.total_records).toLocaleString();
        document.getElementById("stat-kst-time").innerText = data.current_time_kst;
        
        const nextRun = data.scheduler?.next_run_time;
        if (nextRun) {
            const dt = new Date(nextRun);
            document.getElementById("stat-next-batch").innerText = dt.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) + " (00:00 KST)";
        }
    }
}

async function loadLatestWeather() {
    const res = await fetch("/api/weather/latest");
    const json = await res.json();
    if (json.status === "success") {
        latestWeatherData = json.data || [];
        updateLocationView();
        updateComparisonChart();
    }
}

function updateLocationView() {
    let target = latestWeatherData[0];
    if (selectedLocation !== "all") {
        const found = latestWeatherData.find(w => w.location_id === selectedLocation);
        if (found) target = found;
    }

    if (!target) {
        document.getElementById("card-loc-name").innerText = "수집 대기 중...";
        return;
    }

    document.getElementById("card-loc-name").innerText = target.location_name + (selectedLocation === "all" ? " (대표)" : "");
    document.getElementById("card-loc-coords").innerText = `위도 ${target.latitude.toFixed(2)}°, 경도 ${target.longitude.toFixed(2)}°`;
    document.getElementById("card-temp").innerText = target.temperature !== null ? `${target.temperature.toFixed(1)}°C` : "--";
    document.getElementById("card-apparent-temp").innerText = target.apparent_temperature !== null ? `체감 ${target.apparent_temperature.toFixed(1)}°C` : "--";
    document.getElementById("card-humidity").innerText = target.relative_humidity !== null ? `${target.relative_humidity}%` : "--";
    document.getElementById("card-wind").innerText = target.wind_speed !== null ? `${target.wind_speed} m/s` : "--";
    document.getElementById("card-pressure").innerText = target.surface_pressure !== null ? `${target.surface_pressure} hPa` : "--";
    document.getElementById("card-rain").innerText = target.precipitation !== null ? `${target.precipitation} mm` : "0.0 mm";
    document.getElementById("card-last-updated").innerText = new Date(target.timestamp).toLocaleTimeString('ko-KR') + " 수집";
}

async function loadHistory() {
    const url = `/api/weather/history?location_id=${selectedLocation}&limit=100`;
    const res = await fetch(url);
    const json = await res.json();
    if (json.status === "success") {
        historyData = json.data || [];
        renderHistoryTable(historyData);
        updateRealtimeChart(historyData);
    }
}

function renderHistoryTable(data) {
    const tbody = document.getElementById("history-table-body");
    if (!tbody) return;
    if (!data.length) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center py-8 text-gray-500">수집된 이력 데이터가 없습니다.</td></tr>`;
        return;
    }

    tbody.innerHTML = data.map(r => {
        const timeStr = new Date(r.timestamp).toLocaleString('ko-KR', {
            month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit'
        });
        return `
        <tr class="border-b border-gray-800/60 hover:bg-gray-800/40 transition">
            <td class="px-4 py-3 font-mono text-xs text-gray-400">${timeStr}</td>
            <td class="px-4 py-3 font-semibold text-gray-100 flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-blue-400"></span>${r.location_name}
            </td>
            <td class="px-4 py-3 font-bold text-blue-400">${r.temperature !== null ? r.temperature.toFixed(1) + '℃' : '-'}</td>
            <td class="px-4 py-3 text-cyan-300">${r.relative_humidity !== null ? r.relative_humidity + '%' : '-'}</td>
            <td class="px-4 py-3 text-gray-300">${r.wind_speed !== null ? r.wind_speed + ' m/s' : '-'}</td>
            <td class="px-4 py-3 text-gray-300">${r.surface_pressure !== null ? r.surface_pressure + ' hPa' : '-'}</td>
            <td class="px-4 py-3 text-emerald-400">${r.precipitation > 0 ? r.precipitation + ' mm' : '0.0 mm'}</td>
        </tr>
        `;
    }).join("");
}

function filterHistoryTable(keyword) {
    const term = keyword.toLowerCase().trim();
    if (!term) {
        renderHistoryTable(historyData);
        return;
    }
    const filtered = historyData.filter(r => 
        r.location_name.toLowerCase().includes(term) ||
        r.timestamp.includes(term) ||
        String(r.temperature).includes(term)
    );
    renderHistoryTable(filtered);
}

function initCharts() {
    const ctxLive = document.getElementById("realtimeChart")?.getContext("2d");
    if (ctxLive) {
        realtimeChart = new Chart(ctxLive, {
            type: "line",
            data: {
                labels: [],
                datasets: [
                    {
                        label: "기온 (℃)",
                        borderColor: "#3B82F6",
                        backgroundColor: "rgba(59, 130, 246, 0.1)",
                        borderWidth: 2,
                        fill: true,
                        tension: 0.35,
                        data: [],
                        yAxisID: "y"
                    },
                    {
                        label: "습도 (%)",
                        borderColor: "#06B6D4",
                        backgroundColor: "transparent",
                        borderWidth: 1.5,
                        borderDash: [4, 4],
                        tension: 0.35,
                        data: [],
                        yAxisID: "y1"
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: { labels: { color: "#94A3B8", font: { family: "Pretendard" } } },
                    tooltip: { backgroundColor: "rgba(15, 23, 42, 0.9)", titleColor: "#F1F5F9", bodyColor: "#CBD5E1" }
                },
                scales: {
                    x: { ticks: { color: "#64748B", maxTicksLimit: 8 }, grid: { color: "rgba(255,255,255,0.05)" } },
                    y: {
                        type: "linear",
                        display: true,
                        position: "left",
                        ticks: { color: "#3B82F6" },
                        grid: { color: "rgba(255,255,255,0.05)" },
                        title: { display: true, text: "기온 (℃)", color: "#3B82F6" }
                    },
                    y1: {
                        type: "linear",
                        display: true,
                        position: "right",
                        ticks: { color: "#06B6D4" },
                        grid: { drawOnChartArea: false },
                        title: { display: true, text: "습도 (%)", color: "#06B6D4" }
                    }
                }
            }
        });
    }

    const ctxComp = document.getElementById("comparisonChart")?.getContext("2d");
    if (ctxComp) {
        comparisonChart = new Chart(ctxComp, {
            type: "bar",
            data: {
                labels: [],
                datasets: [{
                    label: "현재 기온 (℃)",
                    data: [],
                    backgroundColor: "rgba(99, 102, 241, 0.7)",
                    borderColor: "#6366F1",
                    borderWidth: 1,
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: "#94A3B8" }, grid: { display: false } },
                    y: { ticks: { color: "#94A3B8" }, grid: { color: "rgba(255,255,255,0.05)" } }
                }
            }
        });
    }
}

function updateRealtimeChart(data) {
    if (!realtimeChart) return;
    const sorted = [...data].reverse().slice(-40);
    const labels = sorted.map(d => new Date(d.timestamp).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }));
    const temps = sorted.map(d => d.temperature);
    const humids = sorted.map(d => d.relative_humidity);

    realtimeChart.data.labels = labels;
    realtimeChart.data.datasets[0].data = temps;
    realtimeChart.data.datasets[1].data = humids;
    realtimeChart.update();
}

function updateComparisonChart() {
    if (!comparisonChart || !latestWeatherData.length) return;
    const labels = latestWeatherData.map(d => d.location_name);
    const temps = latestWeatherData.map(d => d.temperature);

    comparisonChart.data.labels = labels;
    comparisonChart.data.datasets[0].data = temps;
    comparisonChart.update();
}

async function loadQualityMetrics() {
    try {
        const res = await fetch("/api/metrics");
        const json = await res.json();
        if (json.status === "success") {
            const m = json.metrics;
            document.getElementById("quality-score-badge").innerText = `${m.overall_quality_score}점 (${m.status})`;
            document.getElementById("quality-score-badge").className = `px-2.5 py-1 text-xs font-bold rounded-full ${
                m.status === 'PASS' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' : 'bg-amber-500/20 text-amber-400 border border-amber-500/40'
            }`;
        }
    } catch (e) {
        console.warn("Quality metrics not loaded yet:", e);
    }
}

async function loadReportsAndMetrics() {
    try {
        const [repRes, metRes] = await Promise.all([
            fetch("/api/reports"),
            fetch("/api/metrics")
        ]);
        const repJson = await repRes.json();
        const metJson = await metRes.json();

        // Render Reports List
        const listEl = document.getElementById("reports-list-body");
        if (listEl && repJson.status === "success") {
            if (!repJson.reports.length) {
                listEl.innerHTML = `<div class="text-gray-500 text-sm py-4">아직 생성된 일일 보고서가 없습니다. 자정(00:00)에 자동 생성되거나 상단 'DVC 파이프라인 수동 실행'을 눌러 즉시 생성할 수 있습니다.</div>`;
            } else {
                listEl.innerHTML = repJson.reports.map(r => `
                <div class="flex items-center justify-between p-4 bg-gray-900/60 rounded-xl border border-gray-800 hover:border-gray-700 transition">
                    <div>
                        <div class="font-bold text-gray-100 flex items-center gap-2">
                            <span>📄</span> ${r.filename}
                        </div>
                        <div class="text-xs text-gray-400 mt-1">생성 일시: ${r.modified_at} • 크기: ${(r.size_bytes / 1024).toFixed(1)} KB</div>
                    </div>
                    <div class="flex gap-2">
                        <button onclick="previewReport('${r.url}')" class="px-3 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition font-medium">
                            미리보기
                        </button>
                        <a href="${r.url}" target="_blank" class="px-3 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 text-gray-200 rounded-lg transition font-medium border border-gray-700">
                            새 창 열기
                        </a>
                    </div>
                </div>
                `).join("");
            }
        }
    } catch (e) {
        console.error("Error loading reports:", e);
    }
}

function previewReport(url) {
    const modal = document.getElementById("report-modal");
    const iframe = document.getElementById("report-iframe");
    if (modal && iframe) {
        iframe.src = url;
        modal.classList.remove("hidden");
    }
}

function closeReportModal() {
    const modal = document.getElementById("report-modal");
    const iframe = document.getElementById("report-iframe");
    if (modal && iframe) {
        iframe.src = "about:blank";
        modal.classList.add("hidden");
    }
}

async function triggerCollectNow() {
    const btn = document.getElementById("btn-collect-now");
    btn.disabled = true;
    btn.innerHTML = `<span class="animate-spin">🌀</span> 수집 중...`;
    try {
        const res = await fetch("/api/collector/trigger", { method: "POST" });
        const json = await res.json();
        if (json.status === "success") {
            showNotification(`${json.collected_count}개 지역 실시간 날씨 데이터 수집 완료!`, "success");
            await loadDashboardData();
        }
    } catch (e) {
        showNotification("수집 요청 중 오류가 발생했습니다.", "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<span>⚡</span> 즉시 수집`;
    }
}

async function triggerPipelineNow() {
    const btn = document.getElementById("btn-run-pipeline");
    btn.disabled = true;
    btn.innerHTML = `<span class="animate-spin">🔄</span> 파이프라인 구동 중...`;
    try {
        const res = await fetch("/api/pipeline/trigger", { method: "POST" });
        const json = await res.json();
        if (json.status === "success") {
            showNotification("DVC 파이프라인 및 품질/분석 보고서가 생성되었습니다!", "success");
            await loadDashboardData();
            if (currentTab === "reports") loadReportsAndMetrics();
        }
    } catch (e) {
        showNotification("파이프라인 실행 중 오류가 발생했습니다.", "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<span>⚙️</span> DVC 파이프라인 실행`;
    }
}

function exportHistoryToCSV() {
    if (!historyData.length) {
        showNotification("내보낼 데이터가 없습니다.", "error");
        return;
    }
    const headers = ["Timestamp", "LocationID", "LocationName", "Latitude", "Longitude", "Temperature(C)", "Humidity(%)", "WindSpeed(m/s)", "Pressure(hPa)", "Precipitation(mm)"];
    const rows = historyData.map(r => [
        `"${r.timestamp}"`,
        `"${r.location_id}"`,
        `"${r.location_name}"`,
        r.latitude,
        r.longitude,
        r.temperature,
        r.relative_humidity,
        r.wind_speed,
        r.surface_pressure,
        r.precipitation
    ]);
    const csvContent = "\uFEFF" + [headers.join(","), ...rows.map(e => e.join(","))].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `weather_history_${selectedLocation}_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function showNotification(msg, type = "info") {
    const toast = document.createElement("div");
    toast.className = `fixed bottom-6 right-6 px-5 py-3 rounded-xl shadow-2xl text-sm font-semibold transition-all duration-300 transform translate-y-4 opacity-0 z-50 flex items-center gap-2 ${
        type === 'success' ? 'bg-emerald-600 text-white' : 'bg-rose-600 text-white'
    }`;
    toast.innerHTML = `<span>${type === 'success' ? '✅' : '⚠️'}</span> ${msg}`;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.classList.remove("translate-y-4", "opacity-0");
    }, 10);
    setTimeout(() => {
        toast.classList.add("opacity-0", "translate-y-4");
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}
