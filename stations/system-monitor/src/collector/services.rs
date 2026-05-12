//! Services collector. Aligns with Python `collect_services()` —
//! cross-references `~/Library/LaunchAgents/*.plist` with `launchctl list`.
//!
//! Phase 1 omits two Python sources (registry.json + workshop_services.py
//! AST parse); they will land when the launcher port is wired. The schema
//! per row is byte-compatible with Python so the dashboard keeps rendering.

use anyhow::Result;
use plist::Value as PlistValue;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::PathBuf;

pub async fn list() -> Result<Vec<Value>> {
    let running = launchctl_running().await;
    let agents_dir = home_dir().join("Library").join("LaunchAgents");

    let mut services: Vec<Value> = Vec::new();
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();

    if agents_dir.is_dir() {
        let mut plists: Vec<PathBuf> = Vec::new();
        if let Ok(rd) = std::fs::read_dir(&agents_dir) {
            for entry in rd.flatten() {
                let p = entry.path();
                let n = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
                if n.ends_with(".plist") || n.ends_with(".plist.disabled") {
                    plists.push(p);
                }
            }
        }
        plists.sort();

        for plist_path in plists {
            let plist = match plist::from_file::<_, PlistValue>(&plist_path) {
                Ok(v) => v,
                Err(_) => continue,
            };
            let dict = match plist.as_dictionary() {
                Some(d) => d,
                None => continue,
            };

            let stem = plist_path
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("")
                .trim_end_matches(".plist")
                .to_string();
            let label = dict
                .get("Label")
                .and_then(|v| v.as_string())
                .map(|s| s.to_string())
                .unwrap_or(stem);

            if seen.contains(&label) {
                continue;
            }
            seen.insert(label.clone());

            let category = if label.contains("pulso") {
                "pulso"
            } else if label.contains("joneshong") {
                "jonathan"
            } else if label.contains("workshop") {
                "workshop"
            } else if label.contains("homebrew") || label.contains("nginx") {
                "infra"
            } else {
                "third-party"
            };

            let has_keepalive = matches!(dict.get("KeepAlive"), Some(PlistValue::Boolean(true)) | Some(PlistValue::Dictionary(_)));
            let run_at_load = matches!(dict.get("RunAtLoad"), Some(PlistValue::Boolean(true)));
            let start_interval = dict.get("StartInterval").and_then(|v| v.as_signed_integer());
            let has_start_cal = dict.get("StartCalendarInterval").is_some();

            let (svc_type, schedule) = if let Some(secs) = start_interval {
                let s = secs as i64;
                let sched = if s < 60 {
                    format!("每 {} 秒", s)
                } else if s < 3600 {
                    format!("每 {} 分鐘", s / 60)
                } else if s < 86400 {
                    format!("每 {} 小時", s / 3600)
                } else {
                    format!("每 {} 天", s / 86400)
                };
                ("periodic", sched)
            } else if has_start_cal {
                ("periodic", "排程".to_string())
            } else if has_keepalive || run_at_load {
                ("service", "常駐".to_string())
            } else {
                ("oneshot", "手動".to_string())
            };

            let is_disabled = plist_path
                .file_name()
                .and_then(|n| n.to_str())
                .map(|n| n.ends_with(".disabled"))
                .unwrap_or(false);

            let run_info = running.get(&label).cloned();
            let pid = run_info.as_ref().and_then(|r| r.pid);
            let exit_status = run_info.as_ref().map(|r| r.exit_status).unwrap_or(0);

            let status: String = if is_disabled {
                "disabled".into()
            } else if pid.is_some() {
                "running".into()
            } else if running.contains_key(&label) {
                if exit_status == 0 {
                    "idle".into()
                } else {
                    format!("error({})", exit_status)
                }
            } else {
                "unloaded".into()
            };

            let log_path = dict
                .get("StandardOutPath")
                .and_then(|v| v.as_string())
                .or_else(|| dict.get("StandardErrorPath").and_then(|v| v.as_string()))
                .map(|s| s.to_string());

            let command = short_command(dict);

            let name = label
                .replace("com.joneshong.", "")
                .replace("com.pulso.", "")
                .replace("com.workshop.", "")
                .replace("homebrew.mxcl.", "");

            services.push(json!({
                "label": label,
                "name": name,
                "category": category,
                "type": svc_type,
                "schedule": schedule,
                "status": status,
                "pid": pid,
                "source": "plist",
                "description": "",
                "command": command,
                "log_path": log_path,
                "plist_path": plist_path.display().to_string(),
            }));
        }
    }

    // Sort: workshop > jonathan > pulso > infra > third-party
    let cat_order = |c: &str| -> i64 {
        match c {
            "workshop" => 0,
            "jonathan" => 1,
            "pulso" => 2,
            "infra" => 3,
            "third-party" => 4,
            _ => 9,
        }
    };
    services.sort_by(|a, b| {
        let ca = a.get("category").and_then(|v| v.as_str()).unwrap_or("");
        let cb = b.get("category").and_then(|v| v.as_str()).unwrap_or("");
        let na = a.get("name").and_then(|v| v.as_str()).unwrap_or("");
        let nb = b.get("name").and_then(|v| v.as_str()).unwrap_or("");
        cat_order(ca).cmp(&cat_order(cb)).then_with(|| na.cmp(nb))
    });

    Ok(services)
}

#[derive(Clone)]
struct LaunchctlRow {
    pid: Option<i64>,
    exit_status: i64,
}

async fn launchctl_running() -> HashMap<String, LaunchctlRow> {
    let mut out: HashMap<String, LaunchctlRow> = HashMap::new();
    let raw = tokio::process::Command::new("launchctl")
        .arg("list")
        .output()
        .await
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .unwrap_or_default();
    for (i, line) in raw.lines().enumerate() {
        if i == 0 {
            continue;
        }
        let parts: Vec<&str> = line.split('\t').collect();
        if parts.len() < 3 {
            continue;
        }
        let pid_str = parts[0];
        let status_str = parts[1];
        let label = parts[2].to_string();
        let pid = if pid_str == "-" {
            None
        } else {
            pid_str.parse::<i64>().ok()
        };
        let exit_status = status_str
            .trim_start_matches('-')
            .parse::<i64>()
            .ok()
            .map(|n| if status_str.starts_with('-') { -n } else { n })
            .unwrap_or(0);
        out.insert(label, LaunchctlRow { pid, exit_status });
    }
    out
}

fn short_command(dict: &plist::Dictionary) -> String {
    if let Some(PlistValue::Array(args)) = dict.get("ProgramArguments") {
        if let Some(first) = args.first().and_then(|v| v.as_string()) {
            let base = first.rsplit('/').next().unwrap_or(first).to_string();
            let rest: Vec<String> = args
                .iter()
                .skip(1)
                .filter_map(|v| v.as_string().map(|s| s.to_string()))
                .collect();
            let full = if rest.is_empty() {
                base
            } else {
                format!("{} {}", base, rest.join(" "))
            };
            return full.chars().take(80).collect();
        }
    }
    if let Some(prog) = dict.get("Program").and_then(|v| v.as_string()) {
        return prog.rsplit('/').next().unwrap_or(prog).to_string();
    }
    "—".to_string()
}

fn home_dir() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/"))
}
