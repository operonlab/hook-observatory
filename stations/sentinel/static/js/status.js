/**
 * Workshop Sentinel — Status Page
 * Polls /api/sentinel/status, /uptime, /incidents every 30s.
 */

const API_BASE = window.location.pathname.includes('/v2/apps/sentinel')
    ? '/v2/apps/sentinel'
    : '';

const POLL_INTERVAL = 30_000;

const STATUS_LABELS = {
    all_operational: 'All Systems Operational',
    maintenance: 'Scheduled Maintenance',
    degraded: 'Degraded Performance',
    partial_outage: 'Partial System Outage',
    major_outage: 'Major System Outage',
};

const SERVICE_DISPLAY = {
    core: 'Core API',
    frontend: 'Frontend (Nginx)',
    'frontend-memvault': 'Frontend — MemVault',
    'frontend-render': 'Frontend Render (Deep)',
    'frontend-memvault-render': 'Frontend MemVault Render (Deep)',
    'hook-observatory': 'Hook Observatory',
    'agent-vista': 'Agent Vista',
    litellm: 'LiteLLM Proxy',
    postgres: 'PostgreSQL',
    redis: 'Redis',
    rustfs: 'RustFS (S3)',
};

// ── Fetch helpers ──

async function fetchJSON(path) {
    try {
        const resp = await fetch(`${API_BASE}${path}`);
        if (!resp.ok) return null;
        return await resp.json();
    } catch {
        return null;
    }
}

// ── Render: Overall Banner ──

function renderBanner(data) {
    const el = document.getElementById('overall-banner');
    if (!data) {
        el.className = 'banner banner--major_outage';
        el.querySelector('.banner__text').textContent = 'Unable to reach Sentinel';
        return;
    }
    const status = data.status || 'all_operational';
    el.className = `banner banner--${status}`;
    el.querySelector('.banner__text').textContent = STATUS_LABELS[status] || status;
}

// ── Render: Service List ──

function renderServices(data) {
    const container = document.getElementById('services-container');
    if (!data || !data.services || data.services.length === 0) {
        container.innerHTML = '<div class="loading">No services detected yet</div>';
        return;
    }

    container.innerHTML = data.services
        .sort((a, b) => (a.service > b.service ? 1 : -1))
        .map(s => {
            const name = SERVICE_DISPLAY[s.service] || s.service;
            const latency = s.response_ms ? `${Math.round(s.response_ms)}ms` : '';
            return `
                <div class="service-row">
                    <span class="service-row__name">${name}</span>
                    <div class="service-row__right">
                        <span class="service-row__latency">${latency}</span>
                        <span class="status-dot status-dot--${s.status}"></span>
                    </div>
                </div>
            `;
        })
        .join('');
}

// ── Render: 90-Day Timeline ──

function renderTimelines(uptimeData) {
    const container = document.getElementById('timelines-container');
    if (!uptimeData || !uptimeData.services || uptimeData.services.length === 0) {
        container.innerHTML = '<div class="loading">No uptime data available</div>';
        return;
    }

    // Build date map for each service
    container.innerHTML = uptimeData.services
        .map(svc => {
            const name = SERVICE_DISPLAY[svc.service] || svc.service;
            const dayMap = {};
            for (const d of svc.days) {
                dayMap[d.date] = d;
            }

            // Generate 90 cells (oldest → newest)
            const cells = [];
            const now = new Date();
            for (let i = 89; i >= 0; i--) {
                const d = new Date(now);
                d.setDate(d.getDate() - i);
                const key = d.toISOString().slice(0, 10);
                const day = dayMap[key];
                const status = day ? day.status : 'no_data';
                const pct = day ? day.uptime_pct : 0;
                cells.push(
                    `<div class="timeline-cell timeline-cell--${status}" data-date="${key}" data-pct="${pct}" data-status="${status}"></div>`
                );
            }

            return `
                <div class="timeline-row">
                    <div class="timeline-row__label">${name}</div>
                    <div class="timeline-bar">${cells.join('')}</div>
                </div>
            `;
        })
        .join('');

    // Attach tooltip events
    attachTooltips();
}

// ── Render: Incidents ──

function renderIncidents(data) {
    const container = document.getElementById('incidents-container');
    if (!data || !data.items || data.items.length === 0) {
        container.innerHTML = '<div class="no-incidents">No recent incidents</div>';
        return;
    }

    container.innerHTML = data.items
        .map(inc => {
            const time = new Date(inc.created_at).toLocaleString('zh-TW');
            return `
                <div class="incident-card">
                    <div class="incident-card__header">
                        <span class="incident-card__title">${inc.title}</span>
                        <span class="incident-card__badge badge--${inc.status}">${inc.status}</span>
                    </div>
                    <div class="incident-card__meta">${inc.service} &middot; ${time}</div>
                    ${inc.detail ? `<div class="incident-card__detail">${inc.detail}</div>` : ''}
                </div>
            `;
        })
        .join('');
}

// ── Tooltip ──

function attachTooltips() {
    const tooltip = document.getElementById('tooltip');

    document.querySelectorAll('.timeline-cell').forEach(cell => {
        cell.addEventListener('mouseenter', e => {
            const date = e.target.dataset.date;
            const pct = e.target.dataset.pct;
            const status = e.target.dataset.status;
            tooltip.textContent = `${date} — ${pct}% uptime (${status})`;
            tooltip.style.display = 'block';
        });

        cell.addEventListener('mousemove', e => {
            tooltip.style.left = `${e.clientX + 12}px`;
            tooltip.style.top = `${e.clientY - 30}px`;
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
}

// Initial load + poll
refresh();
setInterval(refresh, POLL_INTERVAL);
