//! manifest.json — output description shared with downstream operators
//! (`libs/video-ops/final_compose.py` etc.).
//!
//! Schema mirrors the Node renderer's manifest exactly. The Node-side
//! test suite (`tests/render-video.test.mjs`) is the contract source — any
//! field rename here MUST land in lockstep.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Format {
    Png,
    Jpeg,
}

impl Format {
    pub fn ext(&self) -> &'static str {
        match self {
            Format::Png => "png",
            Format::Jpeg => "jpg",
        }
    }

    pub fn cdp_name(&self) -> &'static str {
        match self {
            Format::Png => "png",
            Format::Jpeg => "jpeg",
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct Viewport {
    pub width: u32,
    pub height: u32,
}

/// One contiguous range of frames for a single (chapter, step) pair.
///
/// `start_frame` / `end_frame` are GLOBAL frame indices — even when the
/// renderer only handles one chapter, the indices match their position in
/// the full timeline so parallel workers can write into a shared directory
/// without collisions.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Segment {
    pub chapter_idx: usize,
    pub chapter_id: String,
    pub step: usize,
    pub dur_ms: u64,
    pub start_frame: usize,
    pub end_frame: usize,
    pub frame_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Manifest {
    pub fps: u32,
    pub format: Format,
    pub total_frames: usize,
    pub viewport: Viewport,
    pub segments: Vec<Segment>,
}

/// Build the global plan from a per-chapter duration map.
///
/// `durations` keys are chapter IDs in render order; each value is the list
/// of step durations (ms) for that chapter. Frame counts are
/// `round(dur_ms × fps / 1000)`, with a minimum of 1 frame per step.
pub fn build_plan(durations: &BTreeMap<String, Vec<u64>>, fps: u32) -> (Vec<Segment>, usize) {
    let mut segments = Vec::new();
    let mut cursor: usize = 0;
    for (ch_idx, (chapter_id, steps)) in durations.iter().enumerate() {
        for (step, &dur_ms) in steps.iter().enumerate() {
            let raw = (dur_ms as f64 * fps as f64 / 1000.0).round() as usize;
            let total_frames = raw.max(1);
            segments.push(Segment {
                chapter_idx: ch_idx,
                chapter_id: chapter_id.clone(),
                step,
                dur_ms,
                start_frame: cursor,
                end_frame: cursor + total_frames - 1,
                frame_count: total_frames,
            });
            cursor += total_frames;
        }
    }
    (segments, cursor)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_plan_basic() {
        // BTreeMap iterates in key order. Callers wanting chapter ordering
        // beyond alphabetical must prefix IDs (e.g. "00_intro", "01_body").
        let mut d = BTreeMap::new();
        d.insert("00_intro".into(), vec![1000, 500]);
        d.insert("01_body".into(), vec![2000]);

        let (segs, total) = build_plan(&d, 30);
        assert_eq!(segs.len(), 3);
        // 00_intro/step0: 1000ms × 30fps / 1000 = 30 frames
        assert_eq!(segs[0].chapter_id, "00_intro");
        assert_eq!(segs[0].frame_count, 30);
        assert_eq!(segs[0].start_frame, 0);
        assert_eq!(segs[0].end_frame, 29);
        // 00_intro/step1: 500ms × 30 / 1000 = 15 frames
        assert_eq!(segs[1].frame_count, 15);
        assert_eq!(segs[1].start_frame, 30);
        assert_eq!(segs[1].end_frame, 44);
        // 01_body/step0: 2000ms × 30 / 1000 = 60 frames
        assert_eq!(segs[2].chapter_id, "01_body");
        assert_eq!(segs[2].frame_count, 60);
        assert_eq!(segs[2].start_frame, 45);
        assert_eq!(segs[2].end_frame, 104);
        assert_eq!(total, 105);
    }

    #[test]
    fn build_plan_min_one_frame() {
        let mut d = BTreeMap::new();
        d.insert("a".into(), vec![1]); // 0.03 frames → rounds to 0 → clamp to 1
        let (segs, total) = build_plan(&d, 30);
        assert_eq!(segs[0].frame_count, 1);
        assert_eq!(total, 1);
    }
}
