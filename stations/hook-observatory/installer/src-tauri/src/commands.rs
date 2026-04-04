use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::process::Command;

// ─── Types ───────────────────────────────────────────────────────

#[derive(Debug, Serialize)]
pub struct DepInfo {
    pub name: String,
    pub path: Option<String>,
    pub version: Option<String>,
    pub ok: bool,
}

#[derive(Debug, Serialize)]
pub struct DependencyReport {
    pub python: DepInfo,
    pub claude_code: DepInfo,
    pub git: DepInfo,
}

#[derive(Debug, Serialize)]
pub struct InstallResult {
    pub success: bool,
    pub message: String,
    pub stdout: String,
    pub stderr: String,
}

#[derive(Debug, Serialize)]
pub struct HandlerInfo {
    pub name: String,
    pub category: String,
    pub enabled: bool,
}

#[derive(Debug, Serialize)]
pub struct ConfigData {
    pub handlers: Vec<HandlerInfo>,
    pub raw: serde_json::Value,
}

#[derive(Debug, Deserialize)]
pub struct HandlerToggle {
    pub name: String,
    pub category: String,
    pub enabled: bool,
}

#[derive(Debug, Serialize)]
pub struct ToolDetailInfo {
    pub name: String,
    pub path: Option<String>,
    pub version: Option<String>,
    pub installed: bool,
    pub install_command: String,
    pub required: bool,
}

// ─── Helpers ─────────────────────────────────────────────────────

fn which(cmd: &str) -> Option<String> {
    Command::new("which")
        .arg(cmd)
        .output()
        .ok()
        .and_then(|o| {
            if o.status.success() {
                Some(String::from_utf8_lossy(&o.stdout).trim().to_string())
            } else {
                None
            }
        })
}

fn run_version(cmd: &str, args: &[&str]) -> Option<String> {
    Command::new(cmd)
        .args(args)
        .output()
        .ok()
        .and_then(|o| {
            if o.status.success() {
                let out = String::from_utf8_lossy(&o.stdout).trim().to_string();
                Some(out)
            } else {
                // Some tools output version to stderr
                let err = String::from_utf8_lossy(&o.stderr).trim().to_string();
                if !err.is_empty() {
                    Some(err)
                } else {
                    None
                }
            }
        })
}

fn extract_version(raw: &str) -> String {
    // Extract version number from strings like "Python 3.12.0" or "git version 2.43.0"
    raw.split_whitespace()
        .find(|s| s.chars().next().map_or(false, |c| c.is_ascii_digit()))
        .unwrap_or(raw)
        .to_string()
}

fn observatory_root() -> PathBuf {
    // installer/src-tauri/src/commands.rs -> installer/src-tauri/ -> installer/ -> hook-observatory/
    let manifest_dir = env!("CARGO_MANIFEST_DIR");
    PathBuf::from(manifest_dir)
        .parent() // installer/
        .and_then(|p| p.parent()) // hook-observatory/
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| PathBuf::from("."))
}

// ─── Commands ────────────────────────────────────────────────────

/// Check if required dependencies (Python, Claude Code, Git) are available.
#[tauri::command]
pub fn check_dependencies() -> DependencyReport {
    // Python
    let python_path = which("python3");
    let python_version = python_path
        .as_ref()
        .and_then(|p| run_version(p, &["--version"]))
        .map(|v| extract_version(&v));
    let python_ok = python_version
        .as_ref()
        .map_or(false, |v| v.starts_with("3."));

    // Claude Code
    let claude_path = which("claude");
    let claude_ok = claude_path.is_some();

    // Git
    let git_path = which("git");
    let git_version = git_path
        .as_ref()
        .and_then(|p| run_version(p, &["--version"]))
        .map(|v| extract_version(&v));
    let git_ok = git_path.is_some();

    DependencyReport {
        python: DepInfo {
            name: "Python".into(),
            path: python_path,
            version: python_version,
            ok: python_ok,
        },
        claude_code: DepInfo {
            name: "Claude Code".into(),
            path: claude_path,
            version: None, // claude --version may not exist
            ok: claude_ok,
        },
        git: DepInfo {
            name: "Git".into(),
            path: git_path,
            version: git_version,
            ok: git_ok,
        },
    }
}

/// Run install.py to register hooks into Claude Code.
#[tauri::command]
pub fn install_hooks(python_path: Option<String>) -> InstallResult {
    let root = observatory_root();
    let install_script = root.join("install.py");

    if !install_script.exists() {
        return InstallResult {
            success: false,
            message: format!("install.py not found at {}", install_script.display()),
            stdout: String::new(),
            stderr: String::new(),
        };
    }

    let python = python_path.unwrap_or_else(|| "python3".into());

    let mut cmd = Command::new(&python);
    cmd.arg(install_script.to_str().unwrap());
    cmd.arg("--python");
    cmd.arg(&python);

    match cmd.output() {
        Ok(output) => {
            let stdout = String::from_utf8_lossy(&output.stdout).to_string();
            let stderr = String::from_utf8_lossy(&output.stderr).to_string();
            InstallResult {
                success: output.status.success(),
                message: if output.status.success() {
                    "Installation completed successfully.".into()
                } else {
                    format!("Installation failed with exit code {:?}", output.status.code())
                },
                stdout,
                stderr,
            }
        }
        Err(e) => InstallResult {
            success: false,
            message: format!("Failed to run install.py: {}", e),
            stdout: String::new(),
            stderr: String::new(),
        },
    }
}

/// Read config.example.yaml and return handler list with categories and defaults.
#[tauri::command]
pub fn get_config() -> Result<ConfigData, String> {
    let root = observatory_root();

    // Prefer user config, fall back to example
    let config_path = {
        let user_config = root.join("config.yaml");
        if user_config.exists() {
            user_config
        } else {
            root.join("config.example.yaml")
        }
    };

    let content = std::fs::read_to_string(&config_path)
        .map_err(|e| format!("Cannot read {}: {}", config_path.display(), e))?;

    let yaml: serde_yaml::Value =
        serde_yaml::from_str(&content).map_err(|e| format!("Invalid YAML: {}", e))?;

    let raw = serde_json::to_value(&yaml).map_err(|e| format!("Serialization error: {}", e))?;

    // Extract handlers section
    let mut handlers = Vec::new();

    if let Some(handlers_map) = yaml.get("handlers").and_then(|h| h.as_mapping()) {
        for (category_key, category_val) in handlers_map {
            let category = category_key.as_str().unwrap_or("unknown").to_string();
            if let Some(handler_map) = category_val.as_mapping() {
                for (handler_key, handler_val) in handler_map {
                    let name = handler_key.as_str().unwrap_or("unknown").to_string();
                    let enabled = handler_val.as_bool().unwrap_or(false);
                    handlers.push(HandlerInfo {
                        name,
                        category: category.clone(),
                        enabled,
                    });
                }
            }
        }
    }

    Ok(ConfigData { handlers, raw })
}

/// Save handler toggles to config.yaml, preserving other settings.
#[tauri::command]
pub fn save_config(handlers: Vec<HandlerToggle>) -> Result<String, String> {
    let root = observatory_root();
    let config_path = root.join("config.yaml");
    let example_path = root.join("config.example.yaml");

    // Read existing config or example as base
    let source_path = if config_path.exists() {
        &config_path
    } else {
        &example_path
    };

    let content = std::fs::read_to_string(source_path)
        .map_err(|e| format!("Cannot read {}: {}", source_path.display(), e))?;

    let mut yaml: serde_yaml::Value =
        serde_yaml::from_str(&content).map_err(|e| format!("Invalid YAML: {}", e))?;

    // Group toggles by category
    let mut by_category: BTreeMap<String, BTreeMap<String, bool>> = BTreeMap::new();
    for toggle in &handlers {
        by_category
            .entry(toggle.category.clone())
            .or_default()
            .insert(toggle.name.clone(), toggle.enabled);
    }

    // Update handlers in yaml
    if let Some(handlers_section) = yaml.get_mut("handlers") {
        if let Some(handlers_map) = handlers_section.as_mapping_mut() {
            for (cat_name, cat_handlers) in &by_category {
                let cat_key = serde_yaml::Value::String(cat_name.clone());
                if let Some(existing_cat) = handlers_map.get_mut(&cat_key) {
                    if let Some(existing_map) = existing_cat.as_mapping_mut() {
                        for (handler_name, enabled) in cat_handlers {
                            let h_key = serde_yaml::Value::String(handler_name.clone());
                            existing_map
                                .insert(h_key, serde_yaml::Value::Bool(*enabled));
                        }
                    }
                }
            }
        }
    }

    let output =
        serde_yaml::to_string(&yaml).map_err(|e| format!("Failed to serialize YAML: {}", e))?;

    std::fs::write(&config_path, &output)
        .map_err(|e| format!("Failed to write {}: {}", config_path.display(), e))?;

    Ok(format!("Config saved to {}", config_path.display()))
}

/// Detect tool availability with version and install info.
#[tauri::command]
pub fn detect_tools() -> Vec<ToolDetailInfo> {
    let mut tools = Vec::new();

    // Python
    let py_path = which("python3");
    let py_version = py_path
        .as_ref()
        .and_then(|p| run_version(p, &["--version"]))
        .map(|v| extract_version(&v));
    tools.push(ToolDetailInfo {
        name: "python".into(),
        installed: py_path.is_some(),
        path: py_path,
        version: py_version,
        install_command: "brew install python@3.12".into(),
        required: true,
    });

    // Git
    let git_path = which("git");
    let git_version = git_path
        .as_ref()
        .and_then(|p| run_version(p, &["--version"]))
        .map(|v| extract_version(&v));
    tools.push(ToolDetailInfo {
        name: "git".into(),
        installed: git_path.is_some(),
        path: git_path,
        version: git_version,
        install_command: "brew install git".into(),
        required: true,
    });

    // ruff
    let ruff_path = which("ruff");
    let ruff_version = ruff_path
        .as_ref()
        .and_then(|p| run_version(p, &["--version"]))
        .map(|v| extract_version(&v));
    tools.push(ToolDetailInfo {
        name: "ruff".into(),
        installed: ruff_path.is_some(),
        path: ruff_path,
        version: ruff_version,
        install_command: "brew install ruff".into(),
        required: false,
    });

    // biome
    let biome_path = which("biome");
    let biome_version = biome_path
        .as_ref()
        .and_then(|p| run_version(p, &["--version"]))
        .map(|v| extract_version(&v));
    tools.push(ToolDetailInfo {
        name: "biome".into(),
        installed: biome_path.is_some(),
        path: biome_path,
        version: biome_version,
        install_command: "pnpm add -g @biomejs/biome".into(),
        required: false,
    });

    // gh (GitHub CLI)
    let gh_path = which("gh");
    let gh_version = gh_path
        .as_ref()
        .and_then(|p| run_version(p, &["--version"]))
        .map(|v| extract_version(&v));
    tools.push(ToolDetailInfo {
        name: "gh".into(),
        installed: gh_path.is_some(),
        path: gh_path,
        version: gh_version,
        install_command: "brew install gh".into(),
        required: false,
    });

    tools
}

// ─── Tests ──────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_version() {
        assert_eq!(extract_version("Python 3.12.0"), "3.12.0");
        assert_eq!(extract_version("git version 2.43.0"), "2.43.0");
        assert_eq!(extract_version("3.12.0"), "3.12.0");
    }

    #[test]
    fn test_observatory_root_points_to_package() {
        let root = observatory_root();
        assert!(
            root.join("config.example.yaml").exists(),
            "root should contain config.example.yaml: {:?}",
            root
        );
        assert!(
            root.join("handlers").is_dir(),
            "root should contain handlers/: {:?}",
            root
        );
        assert!(
            root.join("install.py").exists(),
            "root should contain install.py: {:?}",
            root
        );
    }

    #[test]
    fn test_check_dependencies_finds_python_and_git() {
        let report = check_dependencies();
        assert!(report.python.ok, "Python 3.x should be found");
        assert!(report.python.path.is_some());
        assert!(report.python.version.is_some());
        let ver = report.python.version.as_ref().unwrap();
        assert!(ver.starts_with("3."), "Python version should be 3.x, got {}", ver);

        assert!(report.git.ok, "Git should be found");
        assert!(report.git.path.is_some());
    }

    #[test]
    fn test_get_config_returns_handlers() {
        let config = get_config().expect("get_config should succeed");
        assert!(!config.handlers.is_empty(), "should have handlers");

        let names: Vec<&str> = config.handlers.iter().map(|h| h.name.as_str()).collect();
        assert!(names.contains(&"bash_safety"), "missing bash_safety");
        assert!(names.contains(&"auto_format"), "missing auto_format");
        assert!(names.contains(&"secret_scan"), "missing secret_scan");

        let categories: Vec<&str> = config.handlers.iter().map(|h| h.category.as_str()).collect();
        assert!(categories.contains(&"core"), "missing core category");
    }

    #[test]
    fn test_detect_tools_returns_five() {
        let tools = detect_tools();
        assert_eq!(tools.len(), 5);
        let names: Vec<&str> = tools.iter().map(|t| t.name.as_str()).collect();
        assert!(names.contains(&"python"));
        assert!(names.contains(&"git"));
        assert!(names.contains(&"ruff"));
        assert!(names.contains(&"biome"));
        assert!(names.contains(&"gh"));

        for tool in &tools {
            if tool.installed {
                assert!(tool.path.is_some(), "{} marked installed but no path", tool.name);
            }
        }
    }

    #[test]
    fn test_save_config_roundtrip() {
        // Read original state
        let original = get_config().expect("initial get_config");
        let orig_obs = original
            .handlers
            .iter()
            .find(|h| h.name == "observability")
            .expect("observability handler must exist")
            .enabled;

        // Toggle observability
        let toggles: Vec<HandlerToggle> = original
            .handlers
            .iter()
            .map(|h| HandlerToggle {
                name: h.name.clone(),
                category: h.category.clone(),
                enabled: if h.name == "observability" {
                    !h.enabled
                } else {
                    h.enabled
                },
            })
            .collect();

        save_config(toggles).expect("save_config should succeed");

        // Verify toggle applied
        let reloaded = get_config().expect("get_config after save");
        let obs = reloaded
            .handlers
            .iter()
            .find(|h| h.name == "observability")
            .unwrap();
        assert_eq!(obs.enabled, !orig_obs, "observability should be toggled");

        // Restore original
        let restore: Vec<HandlerToggle> = original
            .handlers
            .iter()
            .map(|h| HandlerToggle {
                name: h.name.clone(),
                category: h.category.clone(),
                enabled: h.enabled,
            })
            .collect();
        save_config(restore).expect("restore should succeed");

        // Verify restored
        let final_state = get_config().expect("final get_config");
        let obs_final = final_state
            .handlers
            .iter()
            .find(|h| h.name == "observability")
            .unwrap();
        assert_eq!(obs_final.enabled, orig_obs, "should be restored to original");
    }

    #[test]
    fn test_which_finds_common_tools() {
        assert!(which("git").is_some(), "git should be in PATH");
        assert!(which("python3").is_some(), "python3 should be in PATH");
        assert!(which("nonexistent_tool_xyz123").is_none());
    }
}
