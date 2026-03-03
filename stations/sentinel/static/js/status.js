/**
 * Workshop Sentinel — 服務哨兵 Status Page
 * 每 30 秒輪詢 /api/sentinel/status, /uptime, /incidents
 */

// ── API Base detection (supports /v2/apps/sentinel/ via Nginx) ──

const API_BASE = (() => {
    const p = window.location.pathname;
    if (p.includes('/v2/apps/sentinel')) return '/v2/apps/sentinel';
    return '';
})();

const POLL_INTERVAL = 30_000;
const LOGIN_URL = '/v2/login';
const MAX_INCIDENTS = 5;

// ── Label maps ──

const STATUS_LABELS = {
    all_operational: '所有系統正常運作',
    maintenance:     '排程維護中',
    degraded:        '部分服務效能降級',
    partial_outage:  '部分系統中斷',
    major_outage:    '重大系統中斷',
};

const STATUS_LABELS_SHORT = {
    operational:     '正常',
    degraded:        '降級',
    partial_outage:  '部分中斷',
    major_outage:    '中斷',
    maintenance:     '維護中',
    unknown:         '未知',
};

// ── Service groups (4 categories) ──

const SERVICE_GROUPS = {
    system:   { label: '系統',     order: 0 },
    infra:    { label: '基礎設施', order: 1 },
    internal: { label: '內部服務', order: 2 },
    external: { label: '外部工具', order: 3 },
};

const SERVICE_DISPLAY = {
    // system
    nginx:                      'Nginx',
    orbstack:                   'OrbStack',
    // infra
    postgres:                   'PostgreSQL',
    redis:                      'Redis',
    rustfs:                     'RustFS (S3)',
    lgtm:                       'LGTM Stack',
    'lgtm-render':              'LGTM 渲染 (Deep)',
    litellm:                    'LiteLLM Proxy',
    ollama:                     'Ollama',
    // internal
    core:                       'Core API',
    gateway:                    'Gateway',
    frontend:                   'Workbench',
    'frontend-memvault':        '記憶金庫',
    'frontend-render':          'Workbench 渲染 (Deep)',
    'frontend-memvault-render': '記憶金庫渲染 (Deep)',
    // external
    'hook-observatory':         'Hook 監控台',
    'hook-observatory-render':  'Hook 監控台渲染 (Deep)',
    'agent-vista':              'Agent Vista',
    'agent-vista-render':       'Agent Vista 渲染 (Deep)',
    'system-monitor':           '系統監控',
    'system-monitor-render':    '系統監控渲染 (Deep)',
    'tmux-webui':               'tmux WebUI',
    'tmux-webui-render':        'tmux WebUI 渲染 (Deep)',
    'agent-metrics':            'Agent Metrics',
    'agent-metrics-render':     'Agent Metrics 渲染 (Deep)',
    sentinel:                   '服務哨兵',
    'sentinel-render':          '服務哨兵渲染 (Deep)',
    'file-manager':             '檔案管理',
    'file-manager-render':      '檔案管理渲染 (Deep)',
};

const INCIDENT_LABELS = {
    investigating: '調查中',
    identified:    '已定位',
    repairing:     '修復中',
    resolved:      '已解決',
    escalated:     '已升級',
};

const TOOLTIP_STATUS_NAMES = {
    operational: '正常',
    degraded:    '降級',
    outage:      '中斷',
    no_data:     '無資料',
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
    const diff = Math.floor((Date.now() - d.getTime()) / 1000);
    if (diff < 60)    return '剛才';
    if (diff < 3600)  return `${Math.floor(diff / 60)} 分鐘前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小時前`;
    return d.toLocaleDateString('zh-TW', { month: 'short', day: 'numeric' });
}

function formatTime(isoStr) {
    if (!isoStr) return '';
    return new Date(isoStr).toLocaleString('zh-TW', {
        month:  'numeric',
        day:    'numeric',
        hour:   '2-digit',
        minute: '2-digit',
    });
}

// ── Inline SVG helpers ──

function svgCheckCircle() {
    return `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <path d="M20 6L9 17l-5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`;
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

// ── Render: Service List (grouped) ──

function renderServices(data) {
    const container = document.getElementById('services-container');
    const countEl   = document.getElementById('service-count');

    if (!data?.services?.length) {
        container.innerHTML = '<div class="empty-state"><span class="empty-state__text">尚未偵測到服務</span></div>';
        countEl.textContent = '';
        return;
    }

    const ORDER = { major_outage: 0, partial_outage: 1, degraded: 2, maintenance: 3, operational: 4, unknown: 5 };

    // Group services
    const groups = {};
    for (const s of data.services) {
        const g = s.group || 'external';
        if (!groups[g]) groups[g] = [];
        groups[g].push(s);
    }

    // Sort groups by defined order, sort services within each group by severity
    const sortedGroupKeys = Object.keys(groups).sort(
        (a, b) => (SERVICE_GROUPS[a]?.order ?? 9) - (SERVICE_GROUPS[b]?.order ?? 9)
    );

    const allServices = data.services;
    const healthy = allServices.filter(s => s.status === 'operational').length;
    countEl.textContent = `${healthy} / ${allServices.length} 正常`;

    let animIdx = 2;
    let html = '';

    for (const gKey of sortedGroupKeys) {
        const gInfo    = SERVICE_GROUPS[gKey] || { label: gKey };
        const gServices = groups[gKey].sort((a, b) =>
            (ORDER[a.status] ?? 9) - (ORDER[b.status] ?? 9)
        );
        const gHealthy = gServices.filter(s => s.status === 'operational').length;

        html += `
            <div class="group anim-item" style="--i:${animIdx++}">
                <div class="group__header">
                    <span class="group__title">${escHtml(gInfo.label)}</span>
                    <span class="group__count">${gHealthy} / ${gServices.length}</span>
                </div>
                <div class="group__services">
        `;

        for (const s of gServices) {
            const name        = SERVICE_DISPLAY[s.service] || s.service;
            const latency     = s.response_ms ? `${Math.round(s.response_ms)}ms` : '—';
            const statusLabel = STATUS_LABELS_SHORT[s.status] || s.status;
            html += `
                <div class="svc svc--${s.status} anim-item" style="--i:${animIdx++}">
                    <div class="svc__left">
                        <span class="svc__dot dot--${s.status}" aria-hidden="true"></span>
                        <span class="svc__name">${escHtml(name)}</span>
                    </div>
                    <div class="svc__right">
                        <span class="svc__latency mono">${latency}</span>
                        <span class="svc__badge badge--${s.status}">${statusLabel}</span>
                    </div>
                </div>
            `;
        }

        html += `
                </div>
            </div>
        `;
    }

    container.innerHTML = html;
}

// ── Render: 90-Day Timeline ──

function renderTimelines(uptimeData) {
    const container = document.getElementById('timelines-container');

    if (!uptimeData?.services?.length) {
        container.innerHTML = '<div class="empty-state"><span class="empty-state__text">尚無正常運行時間資料</span></div>';
        return;
    }

    const now = new Date();

    container.innerHTML = uptimeData.services.map(svc => {
        const name   = SERVICE_DISPLAY[svc.service] || svc.service;
        const dayMap = Object.fromEntries(svc.days.map(d => [d.date, d]));

        // Calculate 90-day average uptime %
        let totalPct = 0, totalDays = 0;
        for (const d of svc.days) {
            totalPct += d.uptime_pct;
            totalDays++;
        }
        const avgPct = totalDays > 0 ? (totalPct / totalDays).toFixed(2) : '—';

        // Build 90 cells (oldest → newest, left → right)
        const cells = [];
        for (let i = 89; i >= 0; i--) {
            const d = new Date(now);
            d.setDate(d.getDate() - i);
            const key    = d.toISOString().slice(0, 10);
            const day    = dayMap[key];
            const status = day ? day.status : 'no_data';
            const pct    = day ? day.uptime_pct : 0;
            cells.push(
                `<div class="tl-cell tl-cell--${status}" data-date="${key}" data-pct="${pct}" data-status="${status}" tabindex="-1"></div>`
            );
        }

        return `
            <div class="tl-row">
                <div class="tl-row__header">
                    <span class="tl-row__label">${escHtml(name)}</span>
                    <span class="tl-row__pct">${avgPct === '—' ? '—' : avgPct + '%'}</span>
                </div>
                <div class="tl-bar">${cells.join('')}</div>
            </div>
        `;
    }).join('');

    attachTooltips();
}

// ── Render: Incidents — Vertical Timeline Style ──

function renderIncidents(data) {
    const container = document.getElementById('incidents-container');

    if (!data?.items?.length) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state__icon">${svgCheckCircle()}</div>
                <span class="empty-state__text">目前沒有事件記錄</span>
            </div>
        `;
        return;
    }

    const items    = data.items.slice(0, MAX_INCIDENTS);
    const hasMore  = data.items.length > MAX_INCIDENTS;
    const isLast   = (i) => i === items.length - 1;

    const listHtml = items.map((inc, i) => {
        const statusLabel = INCIDENT_LABELS[inc.status] || inc.status;
        const svcName     = SERVICE_DISPLAY[inc.service] || inc.service;
        const detailHtml  = inc.detail
            ? `<div class="incident__detail">${escHtml(inc.detail)}</div>`
            : '';
        const connectorHtml = isLast(i) ? '' : '<div class="incident__connector"></div>';

        return `
            <div class="incident">
                <div class="incident__timeline-col">
                    <div class="incident__dot incident__dot--${inc.status}"></div>
                    ${connectorHtml}
                </div>
                <div class="incident__body">
                    <div class="incident__top">
                        <span class="incident__title">${escHtml(inc.title)}</span>
                        <span class="incident__badge ibadge--${inc.status}">${statusLabel}</span>
                    </div>
                    <div class="incident__meta mono">
                        <span>${escHtml(svcName)}</span>
                        <span class="incident__meta-sep">·</span>
                        <span>${formatTime(inc.created_at)}</span>
                    </div>
                    ${detailHtml}
                </div>
            </div>
        `;
    }).join('');

    const moreHtml = hasMore
        ? `<div class="incident-more"><a href="${API_BASE}/incidents">查看更多事件 →</a></div>`
        : '';

    container.innerHTML = `<div class="incident-list">${listHtml}</div>${moreHtml}`;
}

// ── Tooltip (timeline cells) ──

function attachTooltips() {
    const tooltip = document.getElementById('tooltip');

    document.querySelectorAll('.tl-cell').forEach(cell => {
        cell.addEventListener('mouseenter', e => {
            const { date, pct, status } = e.target.dataset;
            const statusName = TOOLTIP_STATUS_NAMES[status] || status;
            const pctLabel   = status === 'no_data' ? '—' : `${pct}%`;
            tooltip.textContent = `${date}  ·  ${pctLabel} 正常  (${statusName})`;
            tooltip.style.display = 'block';
        });

        cell.addEventListener('mousemove', e => {
            const x = Math.min(e.clientX + 14, window.innerWidth - 250);
            const y = e.clientY - 38;
            tooltip.style.left = `${x}px`;
            tooltip.style.top  = `${y}px`;
        });

        cell.addEventListener('mouseleave', () => {
            tooltip.style.display = 'none';
        });
    });
}

// ── Escape HTML ──

function escHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
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

    // Update header timestamp
    const updateEl = document.getElementById('last-update');
    if (updateEl) {
        updateEl.textContent = `更新於 ${new Date().toLocaleTimeString('zh-TW', {
            hour:   '2-digit',
            minute: '2-digit',
            second: '2-digit',
        })}`;
    }
}

// ── PWA: Service Worker registration ──

if ('serviceWorker' in navigator) {
    const swPath = `${window.location.pathname.replace(/\/$/, '')}/static/sw.js`;
    navigator.serviceWorker.register(swPath).then((reg) => {
        if (Notification.permission === 'granted') {
            workshopPushSubscribe(reg, '/v2/apps/sentinel/');
        }
    }).catch(() => {});
}

async function workshopPushSubscribe(reg, appScope) {
    try {
        const existing = await reg.pushManager.getSubscription();
        if (existing) return;
        const res = await fetch('/v2/api/notification/vapid-key');
        if (!res.ok) return;
        const { public_key } = await res.json();
        const padding = '='.repeat((4 - public_key.length % 4) % 4);
        const raw = atob((public_key + padding).replace(/-/g, '+').replace(/_/g, '/'));
        const key = new Uint8Array([...raw].map(c => c.charCodeAt(0)));
        const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
        const j = sub.toJSON();
        await fetch('/v2/api/notification/subscriptions', {
            method: 'POST', credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ endpoint: sub.endpoint, keys: { p256dh: j.keys.p256dh, auth: j.keys.auth }, app_scope: appScope }),
        });
    } catch (e) { console.warn('[Push] subscribe failed:', e); }
}

// ── Init ──

refresh();
setInterval(refresh, POLL_INTERVAL);
