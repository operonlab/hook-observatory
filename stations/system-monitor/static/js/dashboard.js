/* System Monitor Dashboard — Auto-refresh + Chart.js */

// ─── HTML Escape ───
function esc(s) {
  const d = document.createElement("div");
  d.textContent = String(s ?? "");
  return d.innerHTML;
}

// ─── Constants ───
const REFRESH_MS = 30_000;
const GAUGE_CIRCUMFERENCE = 100; // matches stroke-dasharray

const COLORS = {
  green: "#a6e3a1",
  yellow: "#f9e2af",
  red: "#f38ba8",
  mauve: "#cba6f7",
  blue: "#89b4fa",
  teal: "#94e2d5",
  text: "#cdd6f4",
  subtext0: "#a6adc8",
  surface0: "#313244",
  surface1: "#45475a",
  mantle: "#181825",
};

// ─── State ───
let autoRefresh = true;
let refreshTimer = null;
let historyChart = null;

// ─── Helpers ───

function pressureColor(level) {
  if (!level) return "normal";
  const l = level.toLowerCase();
  if (l === "danger" || l === "dark-red") return "danger";
  if (l === "critical" || l === "red") return "critical";
  if (l === "warning" || l === "yellow") return "warning";
  return "normal";
}

function makeBadge(level, text) {
  if (!level) return "";
  const cls = pressureColor(level);
  const label = text || level;
  return `<span class="badge badge-${cls}">${label}</span>`;
}

function gaugeStrokeColor(pct) {
  if (pct >= 90) return COLORS.red;
  if (pct >= 75) return COLORS.yellow;
  return COLORS.green;
}

function setGauge(id, pct) {
  const el = document.getElementById(id);
  if (!el) return;
  const p = Math.max(0, Math.min(100, pct || 0));
  const offset = GAUGE_CIRCUMFERENCE - p;
  el.style.strokeDashoffset = offset;
  el.style.stroke = gaugeStrokeColor(p);
}

function fmtGB(bytes) {
  if (bytes == null) return "—";
  return (bytes / (1024 ** 3)).toFixed(1) + " GB";
}

function fmtGBVal(gb) {
  if (gb == null) return "—";
  return gb.toFixed(1) + " GB";
}

function fmtPct(v) {
  if (v == null) return "—";
  return Math.round(v) + "%";
}

function detailRow(label, value) {
  return `<div class="gauge-detail-row"><span class="label">${label}</span><span class="value">${value}</span></div>`;
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("zh-TW") + " " + d.toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" });
}

function fmtBytes(bytes) {
  if (bytes == null) return "—";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 ** 2) return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1024 ** 3) return (bytes / (1024 ** 2)).toFixed(1) + " MB";
  return (bytes / (1024 ** 3)).toFixed(1) + " GB";
}

// ─── Render Functions ───

function renderStatus(data) {
  // System info
  const hw = data.hardware || {};
  const sys = hw.system || {};
  const infoEl = document.getElementById("sys-info");
  if (infoEl) {
    const parts = [data.hostname || sys.hostname, data.os_version || sys.os_version, data.chip || sys.chip].filter(Boolean);
    infoEl.textContent = parts.join(" · ") || "—";
  }

  // Overall pressure
  const badgeEl = document.getElementById("pressure-badge");
  if (badgeEl) badgeEl.innerHTML = makeBadge(data.pressure_level, data.pressure_level);

  // Last updated
  const updEl = document.getElementById("last-updated");
  if (updEl) updEl.textContent = "更新時間：" + fmtTime(data.timestamp);

  // CPU
  const cpu = hw.cpu || {};
  const cpuPct = cpu.usage_pct ?? 0;
  setGauge("cpu-gauge", cpuPct);
  const cpuPctEl = document.getElementById("cpu-pct");
  if (cpuPctEl) cpuPctEl.textContent = fmtPct(cpuPct);
  const cpuDet = document.getElementById("cpu-details");
  if (cpuDet) {
    cpuDet.innerHTML =
      detailRow("負載 1 分鐘", cpu.load_avg_1m ?? "—") +
      detailRow("負載 5 分鐘", cpu.load_avg_5m ?? "—") +
      detailRow("負載 15 分鐘", cpu.load_avg_15m ?? "—");
  }
  const cpuBadge = document.getElementById("cpu-pressure-badge");
  if (cpuBadge) cpuBadge.innerHTML = makeBadge(cpu.pressure);

  // Memory
  const mem = hw.memory || {};
  const memPct = mem.usage_pct ?? 0;
  setGauge("mem-gauge", memPct);
  const memPctEl = document.getElementById("mem-pct");
  if (memPctEl) memPctEl.textContent = fmtPct(memPct);
  const memDet = document.getElementById("mem-details");
  if (memDet) {
    memDet.innerHTML =
      detailRow("已用 / 總計", fmtGBVal(mem.used_gb) + " / " + fmtGBVal(mem.total_gb)) +
      detailRow("應用", fmtGBVal(mem.app_gb)) +
      detailRow("固定", fmtGBVal(mem.wired_gb)) +
      detailRow("壓縮", fmtGBVal(mem.compressed_gb));
  }
  const memBadge = document.getElementById("mem-pressure-badge");
  if (memBadge) memBadge.innerHTML = makeBadge(mem.pressure);

  // Disk
  const disk = data.disk || {};
  const diskPct = disk.usage_pct ?? 0;
  setGauge("disk-gauge", diskPct);
  const diskPctEl = document.getElementById("disk-pct");
  if (diskPctEl) diskPctEl.textContent = fmtPct(diskPct);
  const diskDet = document.getElementById("disk-details");
  if (diskDet) {
    diskDet.innerHTML =
      detailRow("已用", fmtGB(disk.used_bytes)) +
      detailRow("可用", fmtGB(disk.free_bytes)) +
      detailRow("總計", fmtGB(disk.total_bytes));
  }
  const diskBadge = document.getElementById("disk-pressure-badge");
  if (diskBadge) diskBadge.innerHTML = makeBadge(disk.pressure_level);

  // Battery / Temp
  const batt = hw.battery || {};
  const temp = hw.temperature || {};
  const battPct = batt.percent ?? 0;
  setGauge("batt-gauge", battPct);
  const battPctEl = document.getElementById("batt-pct");
  if (battPctEl) battPctEl.textContent = batt.percent != null ? fmtPct(battPct) : "N/A";
  const battDet = document.getElementById("batt-details");
  if (battDet) {
    const charging = batt.charging ? "⚡ 充電中" : "🔋 電池";
    battDet.innerHTML =
      detailRow("狀態", charging) +
      detailRow("CPU 溫度", temp.cpu_temp_c != null ? temp.cpu_temp_c + "°C" : "—") +
      detailRow("GPU 溫度", temp.gpu_temp_c != null ? temp.gpu_temp_c + "°C" : "—");
  }
}

function renderHistory(data) {
  const snaps = (data.snapshots || []).slice().reverse(); // chronological
  const labels = snaps.map((s) => fmtTime(s.timestamp));
  const cpuData = snaps.map((s) => s.cpu_usage_pct);
  const memData = snaps.map((s) => s.memory_usage_pct);
  const diskData = snaps.map((s) => s.disk_usage_pct);

  const ctx = document.getElementById("history-chart");
  if (!ctx) return;

  if (historyChart) {
    historyChart.data.labels = labels;
    historyChart.data.datasets[0].data = cpuData;
    historyChart.data.datasets[1].data = memData;
    historyChart.data.datasets[2].data = diskData;
    historyChart.update("none");
    return;
  }

  historyChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "CPU",
          data: cpuData,
          borderColor: COLORS.blue,
          backgroundColor: COLORS.blue + "22",
          tension: 0.3,
          fill: false,
          pointRadius: 2,
          borderWidth: 2,
        },
        {
          label: "記憶體",
          data: memData,
          borderColor: COLORS.mauve,
          backgroundColor: COLORS.mauve + "22",
          tension: 0.3,
          fill: false,
          pointRadius: 2,
          borderWidth: 2,
        },
        {
          label: "磁碟",
          data: diskData,
          borderColor: COLORS.teal,
          backgroundColor: COLORS.teal + "22",
          tension: 0.3,
          fill: false,
          pointRadius: 2,
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          position: "top",
          labels: { color: COLORS.subtext0, boxWidth: 12, padding: 16, font: { size: 11 } },
        },
        tooltip: {
          backgroundColor: COLORS.mantle,
          titleColor: COLORS.text,
          bodyColor: COLORS.subtext0,
          borderColor: COLORS.surface1,
          borderWidth: 1,
        },
      },
      scales: {
        x: {
          ticks: { color: COLORS.subtext0, maxRotation: 45, font: { size: 10 } },
          grid: { color: COLORS.surface0 },
        },
        y: {
          min: 0,
          max: 100,
          ticks: { color: COLORS.subtext0, callback: (v) => v + "%", font: { size: 10 } },
          grid: { color: COLORS.surface0 },
        },
      },
    },
  });
}

function renderAlerts(data) {
  const list = document.getElementById("alert-list");
  if (!list) return;
  const rawAlerts = data.alerts || [];
  if (rawAlerts.length === 0) {
    list.innerHTML = '<div class="empty">無警報</div>';
    return;
  }

  // Flatten nested structure: each file has { timestamp, overall_pressure, alerts: [...] }
  const flattened = [];
  for (const file of rawAlerts) {
    const ts = file.timestamp;
    const subAlerts = file.alerts || [];
    if (subAlerts.length > 0) {
      for (const sub of subAlerts) {
        flattened.push({
          timestamp: ts,
          pressure: sub.pressure || file.overall_pressure,
          detail: sub.detail || "",
          subsystem: sub.subsystem || "",
        });
      }
    } else {
      // Fallback: treat the file itself as a single alert
      flattened.push({
        timestamp: ts,
        pressure: file.overall_pressure || file.pressure_level || file.level,
        detail: file.detail || file.message || file.summary || "",
        subsystem: file.subsystem || file.source || "",
      });
    }
  }

  list.innerHTML = flattened
    .slice(0, 10)
    .map((a) => {
      const time = fmtDate(a.timestamp);
      const badge = makeBadge(a.pressure);
      return `<div class="alert-item">
        <span class="alert-time">${time}</span>
        ${badge}
        <div class="alert-detail">${esc(a.detail)}<div class="alert-sub">${esc(a.subsystem)}</div></div>
      </div>`;
    })
    .join("");
}

function renderReports(data) {
  const list = document.getElementById("report-list");
  if (!list) return;
  const reports = data.reports || [];
  if (reports.length === 0) {
    list.innerHTML = '<div class="empty">無報告</div>';
    return;
  }
  list.innerHTML = reports
    .map(
      (r) =>
        `<div class="report-item" data-file="${r.filename}">
          <div class="report-header" onclick="toggleReport(this)">
            <span class="report-name">${esc(r.filename)}</span>
            <span class="report-meta">
              <span>${fmtBytes(r.size_bytes)}</span>
              <span>${fmtDate(r.created)}</span>
            </span>
          </div>
          <div class="report-content"></div>
        </div>`
    )
    .join("");
}

async function toggleReport(headerEl) {
  const item = headerEl.closest(".report-item");
  const contentEl = item.querySelector(".report-content");
  if (contentEl.classList.contains("open")) {
    contentEl.classList.remove("open");
    return;
  }
  // Fetch content if not loaded
  if (!contentEl.dataset.loaded) {
    const filename = item.dataset.file;
    try {
      const res = await fetch("reports/" + encodeURIComponent(filename));
      if (res.ok) {
        contentEl.textContent = await res.text();
      } else {
        contentEl.textContent = "無法載入報告。";
      }
    } catch {
      contentEl.textContent = "網路錯誤。";
    }
    contentEl.dataset.loaded = "1";
  }
  contentEl.classList.add("open");
}

// ─── Data Fetching ───

async function fetchAll() {
  try {
    const [statusRes, historyRes, alertsRes, reportsRes] = await Promise.allSettled([
      fetch("status").then((r) => r.json()),
      fetch("history").then((r) => r.json()),
      fetch("alerts").then((r) => r.json()),
      fetch("reports").then((r) => r.json()),
    ]);

    if (statusRes.status === "fulfilled") renderStatus(statusRes.value);
    if (historyRes.status === "fulfilled") renderHistory(historyRes.value);
    if (alertsRes.status === "fulfilled") renderAlerts(alertsRes.value);
    if (reportsRes.status === "fulfilled") renderReports(reportsRes.value);
  } catch (err) {
    console.error("Fetch error:", err);
  }
}

// ─── Auto-Refresh Toggle ───

function setupToggle() {
  const toggle = document.getElementById("auto-refresh-toggle");
  const track = document.getElementById("toggle-track");
  if (!toggle || !track) return;

  toggle.addEventListener("click", () => {
    autoRefresh = !autoRefresh;
    track.classList.toggle("active", autoRefresh);
    if (autoRefresh) {
      startTimer();
    } else {
      stopTimer();
    }
  });
}

function startTimer() {
  stopTimer();
  refreshTimer = setInterval(fetchAll, REFRESH_MS);
}

function stopTimer() {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
}

// ─── Init ───

document.addEventListener("DOMContentLoaded", () => {
  setupToggle();
  fetchAll();
  startTimer();
});
