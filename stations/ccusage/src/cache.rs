use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use std::time::SystemTime;

use crate::types::{DailySummary, FileInfo, UsageEntry};

const CACHE_VERSION: u32 = 5;

#[derive(Serialize, Deserialize)]
struct CacheMeta {
    version: u32,
    last_updated: String,
    /// Map of file path → mtime (as seconds since epoch)
    file_mtimes: HashMap<String, u64>,
}

/// Single consolidated cache of all parsed entries
#[derive(Serialize, Deserialize)]
struct EntriesCache {
    version: u32,
    entries: Vec<CachedEntry>,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct CachedEntry {
    pub timestamp: String,
    pub session_id: String,
    pub message_id: Option<String>,
    pub model: String,
    pub cwd: Option<String>,
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub cache_creation_5m_tokens: u64,
    pub cache_creation_1h_tokens: u64,
    pub cache_read_tokens: u64,
    #[serde(default)]
    pub thinking_tokens: u64,
    #[serde(default)]
    pub speed: Option<String>,
    #[serde(default)]
    pub slug: Option<String>,
    #[serde(default)]
    pub agent_id: Option<String>,
    /// Source JSONL file path (for incremental cache)
    pub source_file: String,
}

impl CachedEntry {
    pub fn to_usage_entry(&self) -> Option<UsageEntry> {
        let timestamp = self.timestamp.parse().ok()?;
        Some(UsageEntry {
            timestamp,
            session_id: self.session_id.clone(),
            message_id: self.message_id.clone(),
            model: self.model.clone(),
            cwd: self.cwd.clone(),
            input_tokens: self.input_tokens,
            output_tokens: self.output_tokens,
            cache_creation_5m_tokens: self.cache_creation_5m_tokens,
            cache_creation_1h_tokens: self.cache_creation_1h_tokens,
            cache_read_tokens: self.cache_read_tokens,
            thinking_tokens: self.thinking_tokens,
            speed: self.speed.clone(),
            slug: self.slug.clone(),
            agent_id: self.agent_id.clone(),
        })
    }

    pub fn from_usage_entry(e: &UsageEntry, source_file: &str) -> Self {
        CachedEntry {
            timestamp: e.timestamp.to_rfc3339(),
            session_id: e.session_id.clone(),
            message_id: e.message_id.clone(),
            model: e.model.clone(),
            cwd: e.cwd.clone(),
            input_tokens: e.input_tokens,
            output_tokens: e.output_tokens,
            cache_creation_5m_tokens: e.cache_creation_5m_tokens,
            cache_creation_1h_tokens: e.cache_creation_1h_tokens,
            cache_read_tokens: e.cache_read_tokens,
            thinking_tokens: e.thinking_tokens,
            speed: e.speed.clone(),
            slug: e.slug.clone(),
            agent_id: e.agent_id.clone(),
            source_file: source_file.to_string(),
        }
    }
}

/// (file_mtimes, cached_entries_raw, usage_entries)
pub type CacheLoadResult = (HashMap<String, u64>, Vec<CachedEntry>, Vec<UsageEntry>);

pub struct CacheManager {
    cache_dir: PathBuf,
}

impl CacheManager {
    pub fn new() -> Self {
        let base = dirs::cache_dir()
            .unwrap_or_else(|| PathBuf::from("/tmp"))
            .join("ccusage");
        let cache_dir = base.join("v5");

        // Clean up old cache versions
        for old in &["v2", "v3", "v4"] {
            let old_dir = base.join(old);
            if old_dir.exists() {
                let _ = std::fs::remove_dir_all(old_dir);
            }
        }

        Self { cache_dir }
    }

    /// Save daily summary to cache
    pub fn save_daily(&self, summary: &DailySummary) -> Result<()> {
        let daily_dir = self.cache_dir.join("daily");
        std::fs::create_dir_all(&daily_dir)?;

        let filename = format!("{}.json", summary.date.format("%Y-%m-%d"));
        let path = daily_dir.join(filename);
        let data = serde_json::to_string(summary)?;
        std::fs::write(path, data)?;
        Ok(())
    }

    /// Save entries with source file tracking for incremental cache
    pub fn save_all_with_sources(
        &self,
        files: &[FileInfo],
        cached_entries: Vec<CachedEntry>,
    ) -> Result<()> {
        std::fs::create_dir_all(&self.cache_dir)?;

        let file_mtimes: HashMap<String, u64> = files
            .iter()
            .map(|f| {
                let mtime = f
                    .mtime
                    .duration_since(SystemTime::UNIX_EPOCH)
                    .map(|d| d.as_secs())
                    .unwrap_or(0);
                (f.path.to_string_lossy().to_string(), mtime)
            })
            .collect();

        let meta = CacheMeta {
            version: CACHE_VERSION,
            last_updated: chrono::Utc::now().to_rfc3339(),
            file_mtimes,
        };

        let meta_data = serde_json::to_string(&meta)?;
        std::fs::write(self.cache_dir.join("meta.json"), meta_data)?;

        let cache = EntriesCache {
            version: CACHE_VERSION,
            entries: cached_entries,
        };

        let entries_data = serde_json::to_vec(&cache)?;
        std::fs::write(self.cache_dir.join("entries.json"), entries_data)?;

        Ok(())
    }

    /// Load cached entries if valid
    pub fn load_all(&self) -> Option<CacheLoadResult> {
        let meta_path = self.cache_dir.join("meta.json");
        let meta_data = match std::fs::read_to_string(&meta_path) {
            Ok(data) => data,
            Err(e) => {
                if meta_path.exists() {
                    eprintln!("warning: cache load failed: {}", e);
                }
                return None;
            }
        };
        let meta: CacheMeta = match serde_json::from_str(&meta_data) {
            Ok(m) => m,
            Err(e) => {
                eprintln!("warning: cache meta parse failed: {}", e);
                return None;
            }
        };

        if meta.version != CACHE_VERSION {
            let _ = std::fs::remove_dir_all(&self.cache_dir);
            return None;
        }

        let entries_path = self.cache_dir.join("entries.json");
        let entries_data = match std::fs::read(&entries_path) {
            Ok(data) => data,
            Err(e) => {
                eprintln!("warning: cache entries load failed: {}", e);
                return None;
            }
        };
        let cache: EntriesCache = match serde_json::from_slice(&entries_data) {
            Ok(c) => c,
            Err(e) => {
                eprintln!("warning: cache entries parse failed: {}", e);
                return None;
            }
        };

        if cache.version != CACHE_VERSION {
            return None;
        }

        let usage_entries: Vec<UsageEntry> = cache
            .entries
            .iter()
            .filter_map(|e| e.to_usage_entry())
            .collect();

        Some((meta.file_mtimes, cache.entries, usage_entries))
    }

    /// Get files that need re-parsing
    pub fn files_needing_reparse<'a>(
        &self,
        files: &'a [FileInfo],
        cached_mtimes: &HashMap<String, u64>,
    ) -> Vec<&'a FileInfo> {
        files
            .iter()
            .filter(|f| {
                let path_str = f.path.to_string_lossy().to_string();
                let current_mtime = f
                    .mtime
                    .duration_since(SystemTime::UNIX_EPOCH)
                    .map(|d| d.as_secs())
                    .unwrap_or(0);

                match cached_mtimes.get(&path_str) {
                    Some(&cached) => current_mtime > cached,
                    None => true,
                }
            })
            .collect()
    }

    /// Get paths of files that were in old cache but no longer exist
    pub fn removed_files(
        &self,
        files: &[FileInfo],
        cached_mtimes: &HashMap<String, u64>,
    ) -> Vec<String> {
        let current_paths: std::collections::HashSet<String> = files
            .iter()
            .map(|f| f.path.to_string_lossy().to_string())
            .collect();

        cached_mtimes
            .keys()
            .filter(|k| !current_paths.contains(k.as_str()))
            .cloned()
            .collect()
    }
}
