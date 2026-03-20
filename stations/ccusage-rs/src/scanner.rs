use anyhow::Result;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::SystemTime;

use crate::types::FileInfo;

/// Scan ~/.claude/projects/ for all JSONL session files
pub fn scan_jsonl_files(base_dir: &Path) -> Result<Vec<FileInfo>> {
    let files = Mutex::new(Vec::new());

    // Use ignore crate's WalkParallel for multi-threaded directory traversal
    let walker = ignore::WalkBuilder::new(base_dir)
        .hidden(false) // Don't skip hidden files
        .git_ignore(false) // Don't respect .gitignore
        .git_global(false)
        .git_exclude(false)
        .build_parallel();

    walker.run(|| {
        Box::new(|entry| {
            let entry = match entry {
                Ok(e) => e,
                Err(_) => return ignore::WalkState::Continue,
            };

            let path = entry.path();
            if path.extension().is_some_and(|ext| ext == "jsonl") && path.is_file() {
                let mtime = path
                    .metadata()
                    .and_then(|m| m.modified())
                    .unwrap_or(SystemTime::UNIX_EPOCH);

                let project = extract_project_name(path, base_dir);

                files.lock().unwrap().push(FileInfo {
                    path: path.to_path_buf(),
                    mtime,
                    project,
                });
            }

            ignore::WalkState::Continue
        })
    });

    Ok(files.into_inner().unwrap())
}

/// Extract project name from file path
/// e.g. ~/.claude/projects/-Users-joneshong-workshop/xxx.jsonl → "workshop"
fn extract_project_name(path: &Path, base_dir: &Path) -> String {
    path.strip_prefix(base_dir)
        .ok()
        .and_then(|rel| rel.components().next())
        .map(|comp| {
            let dir_name = comp.as_os_str().to_string_lossy();
            // Project dir format: -Users-joneshong-xxx or -Users-joneshong-xxx-yyy
            // Extract last meaningful segment
            extract_last_segment(&dir_name)
        })
        .unwrap_or_else(|| "unknown".to_string())
}

fn extract_last_segment(dir_name: &str) -> String {
    // Pattern: -Users-username-project-subpath
    // We want the project name (3rd segment after splitting by -)
    let parts: Vec<&str> = dir_name.split('-').collect();

    // Skip empty first element + "Users" + username = 3 parts
    // Then take remaining as project identifier
    if parts.len() >= 4 {
        // e.g. [""," Users", "joneshong", "workshop"] → "workshop"
        // e.g. ["", "Users", "joneshong", "Claude", "projects", "pulso"] → "Claude/projects/pulso"
        parts[3..].join("-")
    } else {
        dir_name.to_string()
    }
}

/// Get the default projects directory
pub fn default_projects_dir() -> PathBuf {
    dirs::home_dir()
        .expect("Could not find home directory")
        .join(".claude")
        .join("projects")
}
