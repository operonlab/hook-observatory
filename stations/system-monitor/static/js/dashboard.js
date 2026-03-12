/* System Monitor Dashboard — Tab UI + Auto-refresh + Chart.js */

// ─── HTML Escape ───
function esc(s) {
  const d = document.createElement("div");
  d.textContent = String(s ?? "");
  return d.innerHTML;
}

// ─── Constants ───
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
let currentTab = "overview";
let servicesData = [];
let currentCatFilter = "all";
let currentSrcFilter = "all";
let expandedRows = new Set();

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

// ─── Tab Switching ───

function setupTabs() {
  const btns = document.querySelectorAll(".tab-btn");
  btns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      if (tab === currentTab) return;

      // Update buttons
      btns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      // Update panels
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      const panel = document.getElementById("panel-" + tab);
      if (panel) panel.classList.add("active");

      currentTab = tab;

      // Lazy-load tab data
      if (tab === "services") fetchServices();
      if (tab === "guardian") fetchGuardian();
      if (tab === "disk") fetchDiskSummary();
      if (tab === "reports") fetchReports();
    });
  });
}

// ─── Render Functions ───

function renderStatus(data) {
  // System info
  const hw = data.hardware || {};
  const infoEl = document.getElementById("sys-info");
  if (infoEl) {
    const parts = [data.hostname, data.os_version, data.chip].filter(Boolean);
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

  // Battery / Temp — only show when available
  const batt = hw.battery || {};
  const temp = hw.temperature || {};
  const battCard = document.getElementById("batt-card");
  const hasBatt = batt.available === true;
  const hasTemp = temp.available === true;

  if (battCard) {
    battCard.style.display = (hasBatt || hasTemp) ? "" : "none";
  }

  if (hasBatt || hasTemp) {
    const battPct = batt.percent ?? 0;
    setGauge("batt-gauge", hasBatt ? battPct : 0);
    const battPctEl = document.getElementById("batt-pct");
    if (battPctEl) battPctEl.textContent = hasBatt ? fmtPct(battPct) : "—";
    const battDet = document.getElementById("batt-details");
    if (battDet) {
      let html = "";
      if (hasBatt) {
        const charging = batt.charging ? "⚡ 充電中" : "🔋 電池";
        html += detailRow("狀態", charging);
        if (batt.condition) html += detailRow("健康", batt.condition);
        if (batt.cycle_count != null) html += detailRow("循環次數", batt.cycle_count);
      }
      if (hasTemp) {
        html += detailRow("CPU 溫度", temp.cpu_temp_c + "°C");
      }
      battDet.innerHTML = html;
    }
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

function renderTopProcesses(procs) {
  const list = document.getElementById("top-procs-list");
  if (!list) return;
  if (!procs || procs.length === 0) {
    list.innerHTML = '<div class="empty">無執行資料</div>';
    return;
  }
  list.innerHTML = procs
    .slice(0, 3)
    .map((p) => {
      const cpuCls = p.cpu_pct >= 50 ? "val-hot" : p.cpu_pct >= 20 ? "val-warm" : "";
      const memCls = p.mem_mb >= 1024 ? "val-hot" : p.mem_mb >= 256 ? "val-warm" : "";
      const countBadge = p.count > 1 ? ` <span class="proc-count">×${p.count}</span>` : "";
      return `<div class="activity-item">
        <span class="proc-name">${esc(p.name)}${countBadge}</span>
        <span class="proc-stats">
          <span class="${cpuCls}">CPU ${p.cpu_pct}%</span>
          <span class="${memCls}">${p.mem_mb >= 1024 ? (p.mem_mb / 1024).toFixed(1) + " GB" : Math.round(p.mem_mb) + " MB"}</span>
        </span>
      </div>`;
    })
    .join("");
}

// ─── Services Tab ───

function renderServices(data) {
  servicesData = data.services || [];
  const countEl = document.getElementById("svc-count");
  if (countEl) countEl.textContent = `(${servicesData.length})`;
  renderServicesTable();
}

function getFilteredServices() {
  let filtered = servicesData;
  if (currentCatFilter !== "all") {
    filtered = filtered.filter((s) => s.category === currentCatFilter);
  }
  if (currentSrcFilter !== "all") {
    filtered = filtered.filter((s) => s.source === currentSrcFilter);
  }
  return filtered;
}

function statusInfo(s) {
  let cls = "status-idle", label = "閒置";
  if (s.status === "running") { cls = "status-running"; label = "運行中"; }
  else if (s.status === "stopped") { cls = "status-stopped"; label = "已停止"; }
  else if (s.status === "disabled") { cls = "status-disabled"; label = "已停用"; }
  else if (s.status === "unloaded") { cls = "status-unloaded"; label = "未載入"; }
  else if (s.status && s.status.startsWith("error")) { cls = "status-error"; label = s.status; }
  return { cls, label };
}

function svcActions(s) {
  // Only plist services can be controlled via launchctl
  if (s.source !== "plist") return "";
  const label = s.label;
  const btns = [];
  if (s.status === "disabled" || s.status === "unloaded") {
    btns.push(`<button class="action-btn action-enable" onclick="svcAction('${esc(label)}','enable')" title="啟用">▶</button>`);
  }
  if (s.status === "running" || s.status === "idle") {
    btns.push(`<button class="action-btn action-restart" onclick="svcAction('${esc(label)}','restart')" title="重啟">↻</button>`);
    btns.push(`<button class="action-btn action-disable" onclick="svcAction('${esc(label)}','disable')" title="停用">⏹</button>`);
  }
  return btns.join(" ");
}

function renderServicesTable() {
  const tbody = document.getElementById("svc-tbody");
  if (!tbody) return;

  const filtered = getFilteredServices();
  if (filtered.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty">無服務</td></tr>';
    return;
  }

  let html = "";
  for (const s of filtered) {
    const typeCls = `type-${s.type}`;
    const typeLabels = { service: "常駐", periodic: "排程", oneshot: "單次", container: "容器" };
    const typeLabel = typeLabels[s.type] || s.type;
    const { cls: statusCls, label: statusLabel } = statusInfo(s);
    const isExpanded = expandedRows.has(s.label);
    const chevron = isExpanded ? "▾" : "▸";
    const pidInfo = s.pid ? ` <span style="color:var(--subtext0);font-size:0.65rem">PID ${s.pid}</span>` : "";
    const srcBadge = `<span class="source-badge source-${s.source || 'plist'}">${s.source || 'plist'}</span>`;

    html += `<tr class="svc-row ${isExpanded ? 'expanded' : ''}" data-label="${esc(s.label)}">
      <td class="col-expand" onclick="toggleRow('${esc(s.label)}')">${chevron}</td>
      <td>${esc(s.name)}${pidInfo} ${srcBadge}</td>
      <td><span class="type-badge ${typeCls}">${typeLabel}</span></td>
      <td>${esc(s.schedule)}</td>
      <td><span class="${statusCls}"><span class="status-dot"></span><span class="status-text">${statusLabel}</span></span></td>
      <td class="actions-cell">${svcActions(s)}</td>
    </tr>`;

    if (isExpanded) {
      html += `<tr class="svc-detail-row"><td colspan="6">
        <div class="svc-detail">
          <div class="svc-detail-grid">
            <div class="detail-item"><span class="detail-label">Label</span><span class="detail-value">${esc(s.label)}</span></div>
            <div class="detail-item"><span class="detail-label">指令</span><span class="detail-value mono">${esc(s.command || '—')}</span></div>
            <div class="detail-item"><span class="detail-label">說明</span><span class="detail-value">${esc(s.description || '—')}</span></div>
            <div class="detail-item"><span class="detail-label">日誌路徑</span><span class="detail-value mono">${esc(s.log_path || '—')}</span></div>
            ${s.port ? `<div class="detail-item"><span class="detail-label">Port</span><span class="detail-value">${s.port}</span></div>` : ''}
          </div>
          <div class="svc-log-preview" id="log-${CSS.escape(s.label)}">
            <div class="log-header">
              <span>最近日誌</span>
              <button class="action-btn" onclick="fetchServiceLogs('${esc(s.label)}')">刷新</button>
            </div>
            <pre class="log-content">點擊「刷新」載入日誌…</pre>
          </div>
        </div>
      </td></tr>`;
    }
  }
  tbody.innerHTML = html;
}

function toggleRow(label) {
  if (expandedRows.has(label)) {
    expandedRows.delete(label);
  } else {
    expandedRows.add(label);
    // Auto-fetch logs on expand
    setTimeout(() => fetchServiceLogs(label), 50);
  }
  renderServicesTable();
}

async function fetchServiceLogs(label) {
  const logEl = document.getElementById("log-" + CSS.escape(label));
  if (!logEl) return;
  const pre = logEl.querySelector(".log-content");
  if (pre) pre.textContent = "載入中…";
  try {
    const data = await fetch(`services/${encodeURIComponent(label)}/logs?lines=20`).then((r) => r.json());
    if (pre) {
      if (data.error) {
        pre.textContent = data.error;
      } else if (data.lines && data.lines.length > 0) {
        pre.textContent = data.lines.join("\n");
      } else {
        pre.textContent = "（無日誌內容）";
      }
    }
  } catch (err) {
    if (pre) pre.textContent = "載入失敗: " + err.message;
  }
}

async function svcAction(label, action) {
  try {
    const res = await fetch(`services/${encodeURIComponent(label)}/${action}`, { method: "POST" });
    const data = await res.json();
    if (data.status === "ok") {
      // Refresh after short delay for launchctl to settle
      setTimeout(fetchServices, 1000);
    } else {
      alert(`操作失敗: ${data.detail || '未知錯誤'}`);
    }
  } catch (err) {
    alert(`操作失敗: ${err.message}`);
  }
}

function setupServiceFilter() {
  const filter = document.getElementById("svc-filter");
  if (filter) {
    filter.addEventListener("click", (e) => {
      const btn = e.target.closest(".filter-btn");
      if (!btn) return;
      filter.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentCatFilter = btn.dataset.cat;
      renderServicesTable();
    });
  }

  const srcFilter = document.getElementById("svc-source-filter");
  if (srcFilter) {
    srcFilter.addEventListener("click", (e) => {
      const btn = e.target.closest(".filter-btn");
      if (!btn) return;
      srcFilter.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentSrcFilter = btn.dataset.src;
      renderServicesTable();
    });
  }
}

// ─── Guardian Tab ───

function renderGuardian(data) {
  const tbody = document.getElementById("guardian-tbody");
  if (!tbody) return;

  const entries = data.entries || [];
  if (entries.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty">無 Guardian 日誌</td></tr>';
    return;
  }

  tbody.innerHTML = entries
    .map((e) => {
      const levelCls = `level-${e.level}`;
      const kills = e.kills || [];
      const detail = kills.length > 0
        ? kills.map((k) => `${k.process} (${k.mem_mb}MB)`).join(", ")
        : "—";

      return `<tr>
        <td>${esc(e.timestamp)}</td>
        <td><span class="level-badge ${levelCls}">${e.level}</span></td>
        <td>${e.pressure_level}</td>
        <td>${e.total_killed}</td>
        <td>${e.freed_mb > 0 ? e.freed_mb + " MB" : "—"}</td>
        <td><span class="guardian-detail" title="${esc(detail)}">${esc(detail)}</span></td>
      </tr>`;
    })
    .join("");
}

// ─── Data Fetching ───

async function fetchAll() {
  try {
    const [statusRes, historyRes, alertsRes] = await Promise.allSettled([
      fetch("status").then((r) => r.json()),
      fetch("history").then((r) => r.json()),
      fetch("alerts").then((r) => r.json()),
    ]);

    if (statusRes.status === "fulfilled") {
      renderStatus(statusRes.value);
      renderTopProcesses(statusRes.value.top_processes);
    }
    if (historyRes.status === "fulfilled") renderHistory(historyRes.value);
    if (alertsRes.status === "fulfilled") renderAlerts(alertsRes.value);
  } catch (err) {
    console.error("Fetch error:", err);
  }
}

async function fetchServices() {
  try {
    const data = await fetch("services").then((r) => r.json());
    renderServices(data);
  } catch (err) {
    console.error("Services fetch error:", err);
  }
}

async function fetchGuardian() {
  try {
    const data = await fetch("guardian").then((r) => r.json());
    renderGuardian(data);
  } catch (err) {
    console.error("Guardian fetch error:", err);
  }
}

// ─── Disk Tab ───

let diskScanData = null;

function fmtSize(bytes) {
  if (bytes == null || bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + " " + units[i];
}

function renderDiskSummary(data) {
  const pct = data.usage_pct ?? 0;
  setGauge("disk-detail-gauge", pct);
  const pctEl = document.getElementById("disk-detail-pct");
  if (pctEl) pctEl.textContent = fmtPct(pct);
  const infoEl = document.getElementById("disk-detail-info");
  if (infoEl) {
    infoEl.innerHTML =
      detailRow("已用", fmtGB(data.used_bytes)) +
      detailRow("可用", fmtGB(data.free_bytes)) +
      detailRow("總計", fmtGB(data.total_bytes)) +
      detailRow("壓力", makeBadge(data.pressure_level));
  }
}

function renderDiskScan(data) {
  diskScanData = data;

  // Top directories
  const topDirs = document.getElementById("top-dirs-list");
  if (topDirs) {
    const dirs = data.top_dirs || [];
    if (dirs.length === 0) {
      topDirs.innerHTML = '<div class="empty">無資料</div>';
    } else {
      topDirs.innerHTML = dirs.slice(0, 10).map((d) => {
        const pct = data.total_bytes ? ((d.size_bytes || 0) / data.total_bytes * 100).toFixed(1) : 0;
        return `<div class="disk-bar-item">
          <div class="disk-bar-label">${esc(d.path || d.name)}</div>
          <div class="disk-bar-track"><div class="disk-bar-fill" style="width:${Math.min(pct, 100)}%"></div></div>
          <div class="disk-bar-value">${fmtSize(d.size_bytes)} (${pct}%)</div>
        </div>`;
      }).join("");
    }
  }

  // Large files
  const lfTbody = document.getElementById("large-files-tbody");
  if (lfTbody) {
    const files = data.large_files || [];
    if (files.length === 0) {
      lfTbody.innerHTML = '<tr><td colspan="4" class="empty">無大檔案</td></tr>';
    } else {
      lfTbody.innerHTML = files.slice(0, 30).map((f) =>
        `<tr>
          <td title="${esc(f.path)}">${esc(f.path.split("/").pop())}</td>
          <td>${f.size_human || fmtSize(f.size_bytes)}</td>
          <td>${esc(f.modified || "—")}</td>
          <td><button class="action-btn action-disable" onclick="deletePath('${esc(f.path)}','file')">刪除</button></td>
        </tr>`
      ).join("");
    }
  }

  // Stale files
  const sfTbody = document.getElementById("stale-files-tbody");
  if (sfTbody) {
    const files = data.old_files || [];
    if (files.length === 0) {
      sfTbody.innerHTML = '<tr><td colspan="4" class="empty">無過期檔案</td></tr>';
    } else {
      sfTbody.innerHTML = files.slice(0, 30).map((f) =>
        `<tr>
          <td title="${esc(f.path)}">${esc(f.path.split("/").pop())}</td>
          <td>${f.size_human || fmtSize(f.size_bytes)}</td>
          <td>${esc(f.last_access || "—")}</td>
          <td><button class="action-btn action-disable" onclick="deletePath('${esc(f.path)}','file')">刪除</button></td>
        </tr>`
      ).join("");
    }
  }

  // Caches
  const cTbody = document.getElementById("caches-tbody");
  if (cTbody) {
    const caches = data.caches || [];
    if (caches.length === 0) {
      cTbody.innerHTML = '<tr><td colspan="4" class="empty">無快取</td></tr>';
    } else {
      cTbody.innerHTML = caches.map((c) =>
        `<tr>
          <td>${esc(c.name)}</td>
          <td class="mono" style="font-size:0.7rem" title="${esc(c.path)}">${esc(c.path)}</td>
          <td>${c.size || fmtSize(c.size_bytes)}</td>
          <td><button class="action-btn action-restart" onclick="cleanCache('${esc(c.path)}')">清理</button></td>
        </tr>`
      ).join("");
    }
  }
}

async function fetchDiskSummary() {
  try {
    const data = await fetch("disk/summary").then((r) => r.json());
    renderDiskSummary(data);
  } catch (err) {
    console.error("Disk summary error:", err);
  }
}

async function triggerFullScan() {
  const spinner = document.getElementById("disk-scan-spinner");
  if (spinner) spinner.style.display = "";
  try {
    const data = await fetch("disk/scan").then((r) => r.json());
    renderDiskSummary(data);
    renderDiskScan(data);
  } catch (err) {
    console.error("Disk scan error:", err);
  } finally {
    if (spinner) spinner.style.display = "none";
  }
}

async function deletePath(path, type) {
  if (!confirm(`確定刪除？\n${path}`)) return;
  try {
    const res = await fetch("disk/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, type }),
    });
    const data = await res.json();
    if (res.ok) {
      alert(`已刪除，釋放 ${fmtSize(data.freed_bytes)}`);
      triggerFullScan();
    } else {
      alert(`刪除失敗: ${data.detail}`);
    }
  } catch (err) {
    alert(`刪除失敗: ${err.message}`);
  }
}

async function cleanCache(path) {
  if (!confirm(`確定清理快取？\n${path}`)) return;
  try {
    const res = await fetch("disk/clean-cache", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    const data = await res.json();
    if (res.ok) {
      alert(`已清理，釋放 ${fmtSize(data.freed_bytes)}`);
      triggerFullScan();
    } else {
      alert(`清理失敗: ${data.detail}`);
    }
  } catch (err) {
    alert(`清理失敗: ${err.message}`);
  }
}

async function emptyTrash() {
  if (!confirm("確定清空垃圾桶？")) return;
  try {
    const res = await fetch("disk/empty-trash", { method: "POST" });
    const data = await res.json();
    if (res.ok) {
      alert(`已清空垃圾桶，釋放 ${fmtSize(data.freed_bytes)}`);
      triggerFullScan();
    } else {
      alert(`清空失敗: ${data.detail || "未知錯誤"}`);
    }
  } catch (err) {
    alert(`清空失敗: ${err.message}`);
  }
}

// ─── Reports Tab ───

let reportsData = [];
let currentReportTypeFilter = "all";

function renderReportList(data) {
  reportsData = data.reports || [];
  const list = document.getElementById("report-list");
  if (!list) return;

  const filtered = currentReportTypeFilter === "all"
    ? reportsData
    : reportsData.filter((r) => r.type === currentReportTypeFilter);

  if (filtered.length === 0) {
    list.innerHTML = '<div class="empty">無報告</div>';
    return;
  }

  list.innerHTML = filtered.map((r) => {
    const typeLabels = { weekly: "週報", monthly: "月報", daily: "日報" };
    const typeCls = r.type === "monthly" ? "type-periodic" : r.type === "weekly" ? "type-service" : "type-oneshot";
    return `<div class="report-item" onclick="loadReport('${esc(r.filename)}')">
      <span class="type-badge ${typeCls}">${typeLabels[r.type] || r.type}</span>
      <span class="report-name">${esc(r.filename)}</span>
      <span class="report-date">${fmtDate(r.created)}</span>
    </div>`;
  }).join("");
}

async function fetchReports() {
  const spinner = document.getElementById("reports-spinner");
  if (spinner) spinner.style.display = "";
  try {
    const data = await fetch("reports").then((r) => r.json());
    renderReportList(data);
  } catch (err) {
    console.error("Reports fetch error:", err);
  } finally {
    if (spinner) spinner.style.display = "none";
  }
}

async function loadReport(filename) {
  const preview = document.getElementById("report-preview");
  const nameEl = document.getElementById("report-preview-name");
  if (nameEl) nameEl.textContent = filename;
  if (preview) preview.innerHTML = '<div class="empty">載入中…</div>';
  try {
    const data = await fetch(`reports/${encodeURIComponent(filename)}`).then((r) => r.json());
    if (preview && data.content) {
      // Use marked.js if available, otherwise raw
      if (typeof marked !== "undefined") {
        preview.innerHTML = marked.parse(data.content);
      } else {
        preview.innerHTML = `<pre style="white-space:pre-wrap">${esc(data.content)}</pre>`;
      }
    }
  } catch (err) {
    if (preview) preview.innerHTML = `<div class="empty">載入失敗: ${esc(err.message)}</div>`;
  }
}

function setupReportFilter() {
  const filter = document.getElementById("report-type-filter");
  if (filter) {
    filter.addEventListener("click", (e) => {
      const btn = e.target.closest(".filter-btn");
      if (!btn) return;
      filter.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentReportTypeFilter = btn.dataset.rtype;
      renderReportList({ reports: reportsData });
    });
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
      connectSSE();
    } else {
      disconnectSSE();
    }
  });
}

// ─── SSE Connection (replaces setInterval polling) ───

let _sse = null;

function connectSSE() {
  disconnectSSE();
  _sse = new EventSource("events/stream");

  _sse.addEventListener("dashboard", (e) => {
    try {
      const d = JSON.parse(e.data);
      if (d.status) {
        renderStatus(d.status);
        renderTopProcesses(d.status.top_processes);
      }
      if (d.history) renderHistory(d.history);
      if (d.alerts) renderAlerts(d.alerts);
    } catch {}
  });

  _sse.addEventListener("disk", (e) => {
    try { renderDiskSummary(JSON.parse(e.data)); } catch {}
  });

  _sse.onerror = () => {
    disconnectSSE();
    setTimeout(connectSSE, 5000);
  };
}

function disconnectSSE() {
  if (_sse) { _sse.close(); _sse = null; }
}

// ─── Init ───

document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupToggle();
  setupServiceFilter();
  setupReportFilter();
  fetchAll();
  connectSSE();
});
