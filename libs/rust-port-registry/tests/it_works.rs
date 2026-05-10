use workshop_port_registry::{PORTS, get, by_group, HOST};

#[test]
fn loads_all_services() {
    assert_eq!(PORTS.len(), 37, "expected 37 services from yaml");
    assert_eq!(HOST, "127.0.0.1");
}

#[test]
fn core_service_present() {
    let core = get("core").expect("core service missing");
    assert_eq!(core.port, 10000);
    assert_eq!(core.url(), "http://127.0.0.1:10000");
    assert_eq!(core.health_url(), Some("http://127.0.0.1:10000/health".to_string()));
}

#[test]
fn sentinel_uses_legacy_port() {
    let s = get("sentinel").expect("sentinel missing");
    assert_eq!(s.port, 4101);
    assert_eq!(s.health_path, "/api/sentinel/health");
}

#[test]
fn group_lookup() {
    assert_eq!(by_group("core").count(), 4);
    assert_eq!(by_group("docker").count(), 7);
    assert_eq!(by_group("station-ai").count(), 9);
}

#[test]
fn workbench_no_health() {
    let w = get("workbench").expect("workbench missing");
    assert_eq!(w.health_url(), None);  // health_path is empty
}
