/// Workshop port registry — build-time generated from shared/schemas/port_registry.yaml.
///
/// Usage:
/// ```rust
/// use workshop_port_registry::{PORTS, get, by_group, HOST};
/// let core_url = get("core").unwrap().url();   // "http://127.0.0.1:10000"
/// ```

#[derive(Debug, Clone, Copy)]
pub struct ServicePort {
    pub name: &'static str,
    pub port: u16,
    pub group: &'static str,
    pub health_path: &'static str,
    pub env_var: &'static str,
    pub nginx_path: &'static str,
    pub optional: bool,
}

impl ServicePort {
    /// Base URL: `http://{HOST}:{port}`
    pub fn url(&self) -> String {
        format!("http://{}:{}", HOST, self.port)
    }

    /// Health URL: `Some("http://{HOST}:{port}{health_path}")` or `None` if health_path is empty.
    pub fn health_url(&self) -> Option<String> {
        if self.health_path.is_empty() {
            None
        } else {
            Some(format!("{}{}", self.url(), self.health_path))
        }
    }
}

include!(concat!(env!("OUT_DIR"), "/ports.rs"));

/// Look up a service by name.
pub fn get(name: &str) -> Option<&'static ServicePort> {
    PORTS.iter().find(|p| p.name == name)
}

/// Iterate over all services in a given group.
pub fn by_group(group: &str) -> impl Iterator<Item = &'static ServicePort> + use<'_> {
    PORTS.iter().filter(move |p| p.group == group)
}
