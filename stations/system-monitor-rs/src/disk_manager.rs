//! Safe deletion with 6-layer blacklist. Mirrors Python `disk_manager.py`.

use anyhow::Result;
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

const BLACKLIST_PREFIXES: &[&str] = &[
    "/",
    "/System",
    "/Library",
    "/Applications",
    "/usr",
    "/bin",
    "/sbin",
    "/etc",
    "/var",
    "/private",
    "/dev",
];

fn is_safe(path: &Path) -> Result<()> {
    let abs: PathBuf = path
        .canonicalize()
        .unwrap_or_else(|_| path.to_path_buf());
    let s = abs.to_string_lossy();
    // Layer 1: must not be empty / root.
    if s.is_empty() || s == "/" {
        anyhow::bail!("refusing to delete root");
    }
    // Layer 2: depth >= 2.
    if abs.components().count() < 3 {
        anyhow::bail!("refusing depth-1 path: {}", s);
    }
    // Layer 3: blacklist exact prefix match.
    for b in BLACKLIST_PREFIXES {
        if s == *b {
            anyhow::bail!("refusing system path: {}", s);
        }
    }
    // Layer 4: home directory itself.
    if let Ok(home) = std::env::var("HOME") {
        if s == home {
            anyhow::bail!("refusing home root: {}", s);
        }
    }
    // Layer 5: must contain no traversal pattern after canonicalize.
    if s.contains("/..") {
        anyhow::bail!("traversal blocked");
    }
    // Layer 6: must exist.
    if !abs.exists() {
        anyhow::bail!("path does not exist: {}", s);
    }
    Ok(())
}

pub fn delete_path(path: &str) -> Result<Value> {
    let p = PathBuf::from(path);
    is_safe(&p)?;
    let bytes = if p.is_dir() {
        let mut total = 0u64;
        for entry in walkdir::WalkDir::new(&p) {
            if let Ok(e) = entry {
                if let Ok(meta) = e.metadata() {
                    total += meta.len();
                }
            }
        }
        std::fs::remove_dir_all(&p)?;
        total
    } else {
        let meta = std::fs::metadata(&p)?;
        let n = meta.len();
        std::fs::remove_file(&p)?;
        n
    };
    Ok(json!({"ok": true, "path": path, "bytes_freed": bytes}))
}

pub fn clean_cache_dir(path: &str) -> Result<Value> {
    let p = PathBuf::from(path);
    is_safe(&p)?;
    if !p.is_dir() {
        anyhow::bail!("not a directory: {path}");
    }
    let mut freed = 0u64;
    for entry in std::fs::read_dir(&p)? {
        let entry = entry?;
        let child = entry.path();
        if let Ok(meta) = std::fs::metadata(&child) {
            if meta.is_dir() {
                if let Ok(()) = std::fs::remove_dir_all(&child) {
                    freed += dir_size(&child);
                }
            } else if let Ok(()) = std::fs::remove_file(&child) {
                freed += meta.len();
            }
        }
    }
    Ok(json!({"ok": true, "path": path, "bytes_freed": freed}))
}

pub fn empty_trash() -> Result<Value> {
    let home = std::env::var("HOME")?;
    let trash = format!("{home}/.Trash");
    clean_cache_dir(&trash)
}

fn dir_size(p: &Path) -> u64 {
    let mut total = 0u64;
    for e in walkdir::WalkDir::new(p) {
        if let Ok(e) = e {
            if let Ok(m) = e.metadata() {
                total += m.len();
            }
        }
    }
    total
}
