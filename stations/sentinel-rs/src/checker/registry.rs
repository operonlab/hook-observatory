/// 38 light checks mirroring Python sentinel's LIGHT_CHECKS.
/// Port numbers mirror libs/sdk-client/sdk_client/port_registry.py (2026-04-18 snapshot).
pub struct Check {
    pub name: &'static str,
    pub kind: CheckKind,
    pub target: &'static str,
    pub expect_contains: Option<&'static str>,
    pub expect_json: Option<&'static str>,
    pub timeout_sec: u64,
    pub group: &'static str,
    pub optional: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CheckKind {
    Http,
    Shell,
}

pub const CHECKS: &[Check] = &[
    // ── System ─────────────────────────────────────────────
    Check { name: "nginx", kind: CheckKind::Http, target: "http://127.0.0.1:8080/health", expect_contains: None, expect_json: None, timeout_sec: 10, group: "system", optional: false },
    Check { name: "orbstack", kind: CheckKind::Shell, target: "docker info --format '{{.ServerVersion}}'", expect_contains: None, expect_json: None, timeout_sec: 10, group: "system", optional: false },
    Check { name: "port-security", kind: CheckKind::Shell, target: "/Users/joneshong/.local/bin/python3 /Users/joneshong/workshop/scripts/port_audit.py --check", expect_contains: Some("PASS"), expect_json: None, timeout_sec: 15, group: "system", optional: true },
    Check { name: "process-audit", kind: CheckKind::Shell, target: "/Users/joneshong/.local/bin/python3 /Users/joneshong/workshop/scripts/workshop_orphan_reaper.py --json", expect_contains: Some("\"count\": 0"), expect_json: None, timeout_sec: 15, group: "system", optional: true },

    // ── Infra (Docker) ─────────────────────────────────────
    Check { name: "postgres", kind: CheckKind::Shell, target: "docker exec ws-infra-postgres-1 pg_isready -q", expect_contains: None, expect_json: None, timeout_sec: 10, group: "infra", optional: false },
    Check { name: "redis", kind: CheckKind::Shell, target: "docker exec ws-infra-redis-1 redis-cli ping", expect_contains: Some("PONG"), expect_json: None, timeout_sec: 10, group: "infra", optional: false },
    Check { name: "qdrant", kind: CheckKind::Http, target: "http://127.0.0.1:6333/healthz", expect_contains: None, expect_json: None, timeout_sec: 10, group: "infra", optional: false },
    Check { name: "rustfs", kind: CheckKind::Http, target: "http://127.0.0.1:9000/", expect_contains: None, expect_json: None, timeout_sec: 5, group: "infra", optional: false },
    Check { name: "lgtm", kind: CheckKind::Http, target: "http://127.0.0.1:3100/api/health", expect_contains: None, expect_json: None, timeout_sec: 10, group: "infra", optional: true },
    Check { name: "litellm", kind: CheckKind::Http, target: "http://127.0.0.1:4000/health/liveliness", expect_contains: Some("I'm alive!"), expect_json: None, timeout_sec: 10, group: "infra", optional: false },
    Check { name: "bark", kind: CheckKind::Http, target: "http://127.0.0.1:8090/ping", expect_contains: None, expect_json: None, timeout_sec: 10, group: "infra", optional: false },
    Check { name: "mcpproxy", kind: CheckKind::Http, target: "http://127.0.0.1:8808/health", expect_contains: None, expect_json: None, timeout_sec: 10, group: "infra", optional: false },

    // ── Core services ──────────────────────────────────────
    Check { name: "core", kind: CheckKind::Http, target: "http://127.0.0.1:10000/health", expect_contains: None, expect_json: Some(r#"{"status":"healthy"}"#), timeout_sec: 10, group: "internal", optional: false },
    Check { name: "paper", kind: CheckKind::Http, target: "http://127.0.0.1:10010/health", expect_contains: None, expect_json: None, timeout_sec: 10, group: "internal", optional: false },
    Check { name: "intelflow", kind: CheckKind::Http, target: "http://127.0.0.1:10011/health", expect_contains: None, expect_json: None, timeout_sec: 10, group: "internal", optional: false },
    Check { name: "invest", kind: CheckKind::Http, target: "http://127.0.0.1:10012/health", expect_contains: None, expect_json: None, timeout_sec: 10, group: "internal", optional: false },

    // ── Frontend (nginx served) ────────────────────────────
    Check { name: "frontend", kind: CheckKind::Http, target: "http://127.0.0.1:8080/", expect_contains: Some("<div id=\"root\">"), expect_json: None, timeout_sec: 10, group: "internal", optional: false },
    Check { name: "frontend-finance", kind: CheckKind::Http, target: "http://127.0.0.1:8080/finance/", expect_contains: Some("<div id=\"root\">"), expect_json: None, timeout_sec: 10, group: "internal", optional: false },
    Check { name: "frontend-memvault", kind: CheckKind::Http, target: "http://127.0.0.1:8080/memvault/", expect_contains: Some("<div id=\"root\">"), expect_json: None, timeout_sec: 10, group: "internal", optional: false },
    Check { name: "frontend-intelflow", kind: CheckKind::Http, target: "http://127.0.0.1:8080/intelflow/", expect_contains: Some("<div id=\"root\">"), expect_json: None, timeout_sec: 10, group: "internal", optional: false },
    Check { name: "frontend-briefing", kind: CheckKind::Http, target: "http://127.0.0.1:8080/briefing/", expect_contains: Some("<div id=\"root\">"), expect_json: None, timeout_sec: 10, group: "internal", optional: false },
    Check { name: "frontend-dailyos", kind: CheckKind::Http, target: "http://127.0.0.1:8080/dailyos/", expect_contains: Some("<div id=\"root\">"), expect_json: None, timeout_sec: 10, group: "internal", optional: false },
    Check { name: "frontend-paper", kind: CheckKind::Http, target: "http://127.0.0.1:8080/paper/", expect_contains: Some("<div id=\"root\">"), expect_json: None, timeout_sec: 10, group: "internal", optional: false },
    Check { name: "frontend-docvault", kind: CheckKind::Http, target: "http://127.0.0.1:8080/docvault/", expect_contains: Some("<div id=\"root\">"), expect_json: None, timeout_sec: 10, group: "internal", optional: false },

    // ── External stations ──────────────────────────────────
    Check { name: "hook-observatory", kind: CheckKind::Http, target: "http://127.0.0.1:10100/", expect_contains: None, expect_json: None, timeout_sec: 10, group: "external", optional: false },
    Check { name: "session-channel", kind: CheckKind::Http, target: "http://127.0.0.1:10101/health", expect_contains: None, expect_json: None, timeout_sec: 10, group: "external", optional: false },
    Check { name: "agent-vista", kind: CheckKind::Http, target: "http://127.0.0.1:10207/", expect_contains: None, expect_json: None, timeout_sec: 10, group: "external", optional: false },
    Check { name: "system-monitor", kind: CheckKind::Http, target: "http://127.0.0.1:10102/", expect_contains: None, expect_json: None, timeout_sec: 10, group: "external", optional: false },
    Check { name: "tmux-webui", kind: CheckKind::Http, target: "http://127.0.0.1:10105/", expect_contains: None, expect_json: None, timeout_sec: 10, group: "external", optional: false },
    Check { name: "fleet", kind: CheckKind::Http, target: "http://127.0.0.1:10106/health", expect_contains: None, expect_json: None, timeout_sec: 10, group: "external", optional: false },
    Check { name: "agent-metrics", kind: CheckKind::Http, target: "http://127.0.0.1:10103/health", expect_contains: None, expect_json: None, timeout_sec: 10, group: "external", optional: false },
    Check { name: "file-manager", kind: CheckKind::Http, target: "http://127.0.0.1:8850/", expect_contains: None, expect_json: None, timeout_sec: 10, group: "external", optional: false },
    Check { name: "auto-survey", kind: CheckKind::Http, target: "http://127.0.0.1:10300/api/people", expect_contains: None, expect_json: None, timeout_sec: 10, group: "external", optional: false },
    Check { name: "capture-console", kind: CheckKind::Http, target: "http://127.0.0.1:10104/health", expect_contains: None, expect_json: None, timeout_sec: 10, group: "external", optional: false },
    Check { name: "anvil", kind: CheckKind::Http, target: "http://127.0.0.1:10301/docs", expect_contains: None, expect_json: None, timeout_sec: 10, group: "external", optional: false },
    Check { name: "blog", kind: CheckKind::Http, target: "http://127.0.0.1:10302/zh/", expect_contains: Some("JonesHong"), expect_json: None, timeout_sec: 10, group: "external", optional: false },
    Check { name: "cronicle", kind: CheckKind::Http, target: "http://127.0.0.1:4105/api/app/ping", expect_contains: None, expect_json: Some(r#"{"code":0}"#), timeout_sec: 10, group: "external", optional: false },
    Check { name: "sentinel", kind: CheckKind::Http, target: "http://127.0.0.1:4101/api/sentinel/health", expect_contains: None, expect_json: Some(r#"{"status":"healthy"}"#), timeout_sec: 10, group: "system", optional: false },

    // ── AI workers (optional: skipped on connection refused) ──
    Check { name: "stt", kind: CheckKind::Http, target: "http://127.0.0.1:10200/health", expect_contains: None, expect_json: None, timeout_sec: 10, group: "external", optional: true },
    Check { name: "ocr", kind: CheckKind::Http, target: "http://127.0.0.1:10202/health", expect_contains: None, expect_json: None, timeout_sec: 10, group: "external", optional: true },
    Check { name: "tts", kind: CheckKind::Http, target: "http://127.0.0.1:10201/health", expect_contains: None, expect_json: None, timeout_sec: 10, group: "external", optional: true },
    Check { name: "vision", kind: CheckKind::Http, target: "http://127.0.0.1:10203/health", expect_contains: None, expect_json: None, timeout_sec: 10, group: "external", optional: true },
    Check { name: "voice-gateway", kind: CheckKind::Http, target: "http://127.0.0.1:10204/health", expect_contains: None, expect_json: None, timeout_sec: 10, group: "external", optional: true },
    Check { name: "translate", kind: CheckKind::Http, target: "http://127.0.0.1:10205/health", expect_contains: None, expect_json: None, timeout_sec: 10, group: "external", optional: true },
];
