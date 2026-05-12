//! Smoke test for the collector. Asserts the top-level JSON schema lines up
//! with Python `collect_all()` so SDK clients and the dashboard keep working.

use serde_json::Value;
use system_monitor_rs::collector::{collect_all, Collector};

const TOP_KEYS: &[&str] = &[
    "timestamp",
    "hostname",
    "os_version",
    "chip",
    "disk",
    "hardware",
    "pressure_level",
    "top_processes",
];

const HARDWARE_KEYS: &[&str] = &["cpu", "memory", "swap", "temperature", "battery"];

#[tokio::test]
async fn collect_all_top_level_schema_matches_python() {
    let c = Collector::new();
    let snapshot = collect_all(&c).await.expect("collect_all failed");

    let obj = snapshot
        .as_object()
        .expect("collect_all should return a JSON object");

    for key in TOP_KEYS {
        assert!(
            obj.contains_key(*key),
            "missing top-level key {key}; got {:?}",
            obj.keys().collect::<Vec<_>>()
        );
    }

    let hardware = obj
        .get("hardware")
        .and_then(Value::as_object)
        .expect("hardware should be a JSON object");

    for key in HARDWARE_KEYS {
        assert!(
            hardware.contains_key(*key),
            "missing hardware.{key}; got {:?}",
            hardware.keys().collect::<Vec<_>>()
        );
    }

    // top_processes should be a list (matches Python; may be empty if `ps`
    // produced no rows on the test runner).
    assert!(
        snapshot.get("top_processes").is_some_and(Value::is_array),
        "top_processes must be an array"
    );
}

#[tokio::test]
async fn pressure_level_is_one_of_known_strings() {
    let c = Collector::new();
    let snapshot = collect_all(&c).await.expect("collect_all failed");
    let level = snapshot
        .get("pressure_level")
        .and_then(Value::as_str)
        .expect("pressure_level should be a string");
    assert!(
        matches!(level, "normal" | "warning" | "critical" | "danger"),
        "unexpected pressure_level: {level}"
    );
}
