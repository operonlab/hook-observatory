/**
 * Workshop Sentinel — 服務哨兵 Status Page
 * 每 30 秒輪詢 /api/sentinel/status, /uptime, /incidents
 */

const API_BASE = (() => {
    const p = window.location.pathname;
    if (p.includes('/v2/apps/sentinel')) return '/v2/apps/sentinel';
    return '';
})();

const POLL_INTERVAL = 30_000;
const LOGIN_URL = '/v2/login';

const STATUS_LABELS = {
    all_operational: '所有系統正常運作',
    maintenance: '排程維護中',
    degraded: '部分服務效能降級',
    partial_outage: '部分系統中斷',
    major_outage: '重大系統中斷',
};

const STATUS_LABELS_SHORT = {
    operational: '正常',
    degraded: '降級',
    partial_outage: '部分中斷',
    major_outage: '中斷',
    maintenance: '維護中',
    unknown: '未知',
};

const SERVICE_DISPLAY = {
    core: 'Core API',
    frontend: '前端 (Nginx)',
    'frontend-memvault': '前端 — 記憶金庫',
    'frontend-render': '前端渲染 (Deep)',
    'frontend-memvault-render': '記憶金庫渲染 (Deep)',
    'hook-observatory': 'Hook 監控台',
    'agent-vista': 'Agent Vista',
    litellm: 'LiteLLM Proxy',
    postgres: 'PostgreSQL',
    redis: 'Redis',
    rustfs: 'RustFS (S3)',
};

const INCIDENT_LABELS = {
    investigating: '調查中',
    identified: '已定位',
    repairing: '修復中',
    resolved: '已解決',
    escalated: '已升級',
};

// ── Fetch helpers ──

async function fetchJSON(path) {
    try {
        const resp = await fetch(`${API_BASE}${path}`, { credentials: 'include' });
        if (resp.status === 401 || resp.status === 403) {
            window.location.href = LOGIN_URL;
            return null;
        }
        if (!resp.ok) return null;
        return await resp.json();
    } catch {
        return null;
    }
}

// ── Time formatting ──

function timeAgo(isoStr) {
    if (!isoStr) return '';
    const d = new Date(isoStr);
    const now = Date.now();
    const diff = Math.floor((now - d.getTime()) / 1000);
    if (diff < 60) return '剛才';
    if (diff < 3600) return `${Math.floor(diff / 60)} 分鐘前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小時前`;
    return d.toLocaleDateString('zh-TW', { month: 'short', day: 'numeric' });
}

function formatTime(isoStr) {
    if (!isoStr) return '';
    return new Date(isoStr).toLocaleString('zh-TW', {
        month: 'numeric',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });
}

// ── Render: Overall Banner ──

function renderBanner(data) {
    const el = document.getElementById('overall-banner');
    if (!data) {
        el.className = 'banner banner--major_outage';
        el.querySelector('.banner__text').textContent = '無法連線至哨兵服務';
        return;
    }
    const status = data.status || 'all_operational';
    el.className = `banner banner--${status}`;
    el.querySelector('.banner__text').textContent = STATUS_LABELS[status] || status;
}

// ── Render: Service List ──

function renderServices(data) {
    const container = document.getElementById('services-container');
    const countEl = document.getElementById('service-count');

    if (!data?.services?.length) {
        container.innerHTML = '<div class="empty-state"><span class="empty-state__text">尚未偵測到服務</span></div>';
        countEl.textContent = '';
        return;
    }

    const sorted = [...data.services].sort((a, b) => {
        const order = { major_outage: 0, partial_outage: 1, degraded: 2, maintenance: 3, operational: 4, unknown: 5 };
        return (order[a.status] ?? 9) - (order[b.status] ?? 9);
    });

    const healthy = sorted.filter(s => s.status === 'operational').length;
    countEl.textContent = `${healthy}/${sorted.length} 正常`;

    container.innerHTML = sorted.map(s => {
        const name = SERVICE_DISPLAY[s.service] || s.service;
        const latency = s.response_ms ? `${Math.round(s.response_ms)}ms` : '';
        const statusLabel = STATUS_LABELS_SHORT[s.status] || s.status;
        return `
            <div class="svc">
                <div class="svc__left">
                    <span class="svc__dot dot--${s.status}"></span>
                    <span class="svc__name">${name}</span>
                </div>
                <div class="svc__right">
                    <span class="svc__latency">${latency}</span>
                    <span class="svc__badge badge--${s.status}">${statusLabel}</span>
                </div>
            </div>
        `;
    }).join('');
}

// ── Render: 90-Day Timeline ──

function renderTimelines(uptimeData) {
    const container = document.getElementById('timelines-container');

    if (!uptimeData?.services?.length) {
        container.innerHTML = '<div class="empty-state"><span class="empty-state__text">尚無正常運行時間資料</span></div>';
        return;
    }

    container.innerHTML = uptimeData.services.map(svc => {
        const name = SERVICE_DISPLAY[svc.service] || svc.service;
        const dayMap = Object.fromEntries(svc.days.map(d => [d.date, d]));

        // Calculate overall uptime %
        let totalPct = 0, totalDays = 0;
        for (const d of svc.days) {
            totalPct += d.uptime_pct;
            totalDays++;
        }
        const avgPct = totalDays > 0 ? (totalPct / totalDays).toFixed(2) : '—';

        // Generate 90 cells
        const cells = [];
        const now = new Date();
        for (let i = 89; i >= 0; i--) {
            const d = new Date(now);
            d.setDate(d.getDate() - i);
            const key = d.toISOString().slice(0, 10);
            const day = dayMap[key];
            const status = day ? day.status : 'no_data';
            const pct = day ? day.uptime_pct : 0;
            cells.push(`<div class="tl-cell tl-cell--${status}" data-date="${key}" data-pct="${pct}" data-status="${status}"></div>`);
        }

        return `
            <div class="tl-row">
                <div class="tl-row__header">
                    <span class="tl-row__label">${name}</span>
                    <span class="tl-row__pct">${avgPct}%</span>
                </div>
                <div class="tl-bar">${cells.join('')}</div>
            </div>
        `;
    }).join('');

    attachTooltips();
}

// ── Render: Incidents ──

function renderIncidents(data) {
    const container = document.getElementById('incidents-container');

    if (!data?.items?.length) {
        container.innerHTML = `
            <div class="empty-state">
                <span class="empty-state__icon">✓</span>
                <span class="empty-state__text">目前沒有事件記錄</span>
            </div>
        `;
        return;
    }

    container.innerHTML = data.items.map(inc => {
        const statusLabel = INCIDENT_LABELS[inc.status] || inc.status;
        return `
            <div class="incident">
                <div class="incident__top">
                    <span class="incident__title">${inc.title}</span>
                    <span class="incident__badge ibadge--${inc.status}">${statusLabel}</span>
                </div>
                <div class="incident__meta">${SERVICE_DISPLAY[inc.service] || inc.service} · ${formatTime(inc.created_at)}</div>
                ${inc.detail ? `<div class="incident__detail">${inc.detail}</div>` : ''}
            </div>
        `;
    }).join('');
}

// ── Tooltip ──

function attachTooltips() {
    const tooltip = document.getElementById('tooltip');
    const statusNames = { operational: '正常', degraded: '降級', outage: '中斷', no_data: '無資料' };

    document.querySelectorAll('.tl-cell').forEach(cell => {
        cell.addEventListener('mouseenter', e => {
            const { date, pct, status } = e.target.dataset;
            tooltip.textContent = `${date} — ${pct}% 正常 (${statusNames[status] || status})`;
            tooltip.style.display = 'block';
        });

        cell.addEventListener('mousemove', e => {
            const x = Math.min(e.clientX + 12, window.innerWidth - 220);
            tooltip.style.left = `${x}px`;
            tooltip.style.top = `${e.clientY - 36}px`;
        });

        cell.addEventListener('mouseleave', () => {
            tooltip.style.display = 'none';
        });
    });
}

// ── Poll Loop ──

async function refresh() {
    const [statusData, uptimeData, incidentData] = await Promise.all([
        fetchJSON('/api/sentinel/status'),
        fetchJSON('/api/sentinel/uptime?days=90'),
        fetchJSON('/api/sentinel/incidents?page=1&page_size=10'),
    ]);

    renderBanner(statusData);
    renderServices(statusData);
    renderTimelines(uptimeData);
    renderIncidents(incidentData);

    // Update header time
    const updateEl = document.getElementById('last-update');
    if (updateEl) {
        updateEl.textContent = `更新於 ${new Date().toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`;
    }
}

// ── PWA registration ──

if ('serviceWorker' in navigator) {
    const swPath = `${window.location.pathname.replace(/\/$/, '')}/static/sw.js`;
    navigator.serviceWorker.register(swPath).catch(() => {});
}

// ── Init ──

refresh();
setInterval(refresh, POLL_INTERVAL);
