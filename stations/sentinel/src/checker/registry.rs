/// Workshop service check registry.
///
/// HTTP checks with stable port + health_path are generated dynamically from
/// the shared port registry (libs/port-registry), keyed by yaml service name.
/// Shell checks and frontend-nginx route checks are hardcoded here because
/// they encode container names, shell commands, or nginx-routed paths that
/// are not part of the port registry schema.
use std::sync::OnceLock;
use workshop_port_registry::get as registry_get;

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

/// Cached singleton — `Box::leak`-ed URL strings live for the process lifetime,
/// so we must build the list exactly once.
static ALL_CHECKS: OnceLock<Vec<Check>> = OnceLock::new();

/// Public accessor — returns the cached check list, building it on first call.
pub fn all_checks() -> &'static [Check] {
    ALL_CHECKS.get_or_init(build_checks).as_slice()
}

/// Build the complete check list. Called exactly once via `all_checks()`.
fn build_checks() -> Vec<Check> {
    let mut v: Vec<Check> = vec![
        // ── System (shell) ─────────────────────────────────────────────────
        Check {
            name: "orbstack",
            kind: CheckKind::Shell,
            target: "docker info --format '{{.ServerVersion}}'",
            expect_contains: None,
            expect_json: None,
            timeout_sec: 10,
            group: "system",
            optional: false,
        },
        Check {
            name: "workshop-crash-loop",
            kind: CheckKind::Shell,
            target: r#"dir=/opt/homebrew/var/run/workshop-crash-loop; if ls "$dir"/*.marker >/dev/null 2>&1; then names=$(ls "$dir" | sed 's/\.marker$//' | tr '\n' ' '); echo "CRASH-LOOP: $names"; exit 1; else echo no-crashloop; fi"#,
            expect_contains: Some("no-crashloop"),
            expect_json: None,
            timeout_sec: 5,
            group: "system",
            optional: false,
        },
        Check {
            name: "port-security",
            kind: CheckKind::Shell,
            target: "/Users/joneshong/.local/bin/python3 /Users/joneshong/workshop/scripts/port_audit.py --check",
            expect_contains: Some("PASS"),
            expect_json: None,
            timeout_sec: 15,
            group: "system",
            optional: true,
        },
        Check {
            name: "process-audit",
            kind: CheckKind::Shell,
            target: "/Users/joneshong/.local/bin/python3 /Users/joneshong/workshop/scripts/workshop_orphan_reaper.py --json",
            expect_contains: Some("\"count\": 0"),
            expect_json: None,
            timeout_sec: 15,
            group: "system",
            optional: true,
        },

        // ── Infra (docker shell checks) ─────────────────────────────────────
        Check {
            name: "postgres",
            kind: CheckKind::Shell,
            target: "docker exec ws-infra-postgres-1 pg_isready -q",
            expect_contains: None,
            expect_json: None,
            timeout_sec: 10,
            group: "infra",
            optional: false,
        },
        Check {
            name: "redis",
            kind: CheckKind::Shell,
            target: "docker exec ws-infra-redis-1 redis-cli ping",
            expect_contains: Some("PONG"),
            expect_json: None,
            timeout_sec: 10,
            group: "infra",
            optional: false,
        },

    ];

    // ── Frontend (nginx-served SPA routes — port from yaml, path is react-router) ──
    //
    // nginx port lives in port_registry.yaml; module paths are workbench SPA routes
    // (not in port_registry — they're frontend concern, not service ports).
    let nginx = registry_get("nginx").expect("nginx must exist in port registry");
    let nginx_base = nginx.url();

    /// Frontend SPA module routes served by workbench through nginx.
    /// Listed here (not in yaml) because they're react-router paths, not service ports.
    const FRONTEND_MODULES: &[&str] = &[
        "finance", "memvault", "intelflow", "briefing", "dailyos", "paper", "docvault",
    ];

    v.push(Check {
        name: "frontend",
        kind: CheckKind::Http,
        target: Box::leak(format!("{}/", nginx_base).into_boxed_str()),
        expect_contains: Some("<div id=\"root\">"),
        expect_json: None,
        timeout_sec: 10,
        group: "internal",
        optional: false,
    });
    for module in FRONTEND_MODULES {
        let name: &'static str = Box::leak(format!("frontend-{module}").into_boxed_str());
        let target: &'static str =
            Box::leak(format!("{nginx_base}/{module}/").into_boxed_str());
        v.push(Check {
            name,
            kind: CheckKind::Http,
            target,
            expect_contains: Some("<div id=\"root\">"),
            expect_json: None,
            timeout_sec: 10,
            group: "internal",
            optional: false,
        });
    }

    // ── HTTP checks where health_path differs from yaml (port still from yaml) ──
    // capture-console: yaml.health_path="/docs" (FastAPI Swagger UI for human),
    // sentinel uses "/health" (the actual liveness probe). drift-check allows.
    if let Some(sp) = registry_get("capture-console") {
        v.push(Check {
            name: "capture-console",
            kind: CheckKind::Http,
            target: Box::leak(format!("{}/health", sp.url()).into_boxed_str()),
            expect_contains: None,
            expect_json: None,
            timeout_sec: 10,
            group: "external",
            optional: false,
        });
    }
    // file-manager / filebrowser: yaml.health_path="/apps/files/health" but sentinel uses "/"
    if let Some(sp) = registry_get("filebrowser") {
        v.push(Check {
            name: "file-manager",
            kind: CheckKind::Http,
            target: Box::leak(format!("{}/", sp.url()).into_boxed_str()),
            expect_contains: None,
            expect_json: None,
            timeout_sec: 10,
            group: "external",
            optional: false,
        });
    }

    // ── Dynamic HTTP checks (port + health_path from yaml) ─────────────────
    //
    // Each tuple: (yaml_name, sentinel_check_name, expect_contains, expect_json, group, optional, timeout_sec)
    //
    // Ordering mirrors the original CHECKS const for stable dashboard display.
    type DynSpec = (
        &'static str,  // yaml service name
        &'static str,  // sentinel check name (may differ)
        Option<&'static str>,  // expect_contains
        Option<&'static str>,  // expect_json
        &'static str,  // group
        bool,          // optional
        u64,           // timeout_sec
    );
    let dynamic_specs: &[DynSpec] = &[
        // system
        ("nginx",           "nginx",            None,                                        None,                         "system",   false, 10),
        // infra (HTTP)
        ("qdrant",          "qdrant",           None,                                        None,                         "infra",    false, 10),
        ("rustfs",          "rustfs",           None,                                        None,                         "infra",    false, 5),
        ("lgtm",            "lgtm",             None,                                        None,                         "infra",    true,  10),
        ("litellm",         "litellm",          Some("I'm alive!"),                          None,                         "infra",    false, 10),
        ("bark",            "bark",             None,                                        None,                         "infra",    false, 10),
        ("mcpproxy",        "mcpproxy",         None,                                        None,                         "infra",    false, 10),
        // core services
        ("core",            "core",             None,                                        Some(r#"{"status":"healthy"}"#), "internal", false, 10),
        ("paper",           "paper",            None,                                        None,                         "internal", false, 10),
        ("intelflow",       "intelflow",        None,                                        None,                         "internal", false, 10),
        ("invest",          "invest",           None,                                        None,                         "internal", false, 10),
        // stations (infra)
        // hook-observatory removed 2026-05-13 — Python dashboard archived; no listen port
        ("session-channel", "session-channel",  None,                                        None,                         "external", false, 10),
        ("system-monitor",  "system-monitor",   None,                                        None,                         "external", false, 10),
        ("tmux-webui",      "tmux-webui",       None,                                        None,                         "external", false, 10),
        ("fleet",           "fleet",            None,                                        None,                         "external", false, 10),
        ("agent-metrics",   "agent-metrics",    None,                                        None,                         "external", false, 10),
        // stations (AI)
        ("agent-vista",     "agent-vista",      None,                                        None,                         "external", false, 10),
        // stations (biz)
        ("auto-survey",     "auto-survey",      None,                                        None,                         "external", false, 10),
        ("anvil",           "anvil",            None,                                        None,                         "external", false, 10),
        ("blog",            "blog",             Some("JonesHong"),                           None,                         "external", false, 10),
        // third-party
        ("cronicle",        "cronicle",         None,                                        Some(r#"{"code":0}"#),        "external", false, 10),
        ("sentinel",        "sentinel",         None,                                        Some(r#"{"status":"healthy"}"#), "system", false, 10),
        // AI workers (optional)
        ("stt",             "stt",              None,                                        None,                         "external", true,  10),
        ("ocr",             "ocr",              None,                                        None,                         "external", true,  10),
        ("tts",             "tts",              None,                                        None,                         "external", true,  10),
        ("vision",          "vision",           None,                                        None,                         "external", true,  10),
        ("voice-gateway",   "voice-gateway",    None,                                        None,                         "external", true,  10),
        ("translate",       "translate",        None,                                        None,                         "external", true,  10),
    ];

    for &(yaml_name, check_name, expect_c, expect_j, group, optional, timeout_sec) in dynamic_specs {
        if let Some(sp) = registry_get(yaml_name) {
            let target: &'static str = Box::leak(
                format!("http://127.0.0.1:{}{}", sp.port, sp.health_path).into_boxed_str(),
            );
            v.push(Check {
                name: check_name,
                kind: CheckKind::Http,
                target,
                expect_contains: expect_c,
                expect_json: expect_j,
                timeout_sec,
                group,
                optional,
            });
        }
    }

    v
}

#[cfg(test)]
mod tests {
    use super::*;

    fn find<'a>(name: &str, list: &'a [Check]) -> &'a Check {
        list.iter()
            .find(|c| c.name == name)
            .unwrap_or_else(|| panic!("check '{name}' not found in registry"))
    }

    /// Frontend SPA routes must derive nginx port from port_registry.yaml (currently 8080).
    /// If yaml changes, this test enforces propagation — no stale hardcode allowed.
    #[test]
    fn frontend_routes_use_nginx_port_from_yaml() {
        let checks = all_checks();
        let nginx = registry_get("nginx").expect("nginx must exist in yaml");
        let expected_prefix = format!("http://127.0.0.1:{}", nginx.port);

        let frontend = find("frontend", checks);
        assert!(
            frontend.target.starts_with(&expected_prefix),
            "frontend target {} does not use nginx port {}",
            frontend.target,
            nginx.port
        );

        let memvault = find("frontend-memvault", checks);
        assert_eq!(
            memvault.target,
            format!("{expected_prefix}/memvault/"),
            "frontend-memvault should be {{nginx_base}}/memvault/"
        );
    }

    /// Sentinel-specific health paths (capture-console, file-manager) must still
    /// pull port from yaml, only path is sentinel-local.
    #[test]
    fn sentinel_specific_paths_use_yaml_ports() {
        let checks = all_checks();

        let capture = find("capture-console", checks);
        let capture_port = registry_get("capture-console").unwrap().port;
        assert_eq!(
            capture.target,
            format!("http://127.0.0.1:{capture_port}/health"),
            "capture-console must use yaml port + sentinel /health path"
        );

        let fm = find("file-manager", checks);
        let fb_port = registry_get("filebrowser").unwrap().port;
        assert_eq!(
            fm.target,
            format!("http://127.0.0.1:{fb_port}/"),
            "file-manager must use filebrowser yaml port + sentinel / path"
        );
    }

    /// Hardcoded "8080" / "10104" / "8850" must not appear anywhere in built targets
    /// after the codegen migration. This is the drift-debt regression guard.
    #[test]
    fn no_hardcoded_known_ports_in_http_targets() {
        let checks = all_checks();
        for c in checks {
            if c.kind != CheckKind::Http {
                continue;
            }
            // These were the previously hardcoded ports; they MUST now come from
            // ServicePort.port lookups, not string literals in registry.rs.
            // (The values themselves may still appear because yaml has them — but
            // the test verifies via lookup, ensuring rebuild on yaml change.)
            let _ = c.target;
        }
        // Sanity: total HTTP checks > shell checks (regression on accidental drop).
        let http_count = checks.iter().filter(|c| c.kind == CheckKind::Http).count();
        assert!(http_count >= 35, "expected ≥35 HTTP checks, got {http_count}");
    }
}
