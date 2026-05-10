use std::{env, fs, path::PathBuf};
use serde::Deserialize;

#[derive(Deserialize)]
struct Registry {
    host: String,
    services: Vec<Svc>,
}

#[derive(Deserialize)]
struct Svc {
    name: String,
    port: u16,
    group: String,
    #[serde(default = "default_health")]
    health_path: String,
    #[serde(default)]
    env_var: String,
    #[serde(default)]
    nginx_path: String,
    #[serde(default)]
    optional: bool,
}

fn default_health() -> String {
    "/health".into()
}

fn main() {
    let yaml_path = "../../shared/schemas/port_registry.yaml";
    println!("cargo:rerun-if-changed={}", yaml_path);

    let raw = fs::read_to_string(yaml_path)
        .unwrap_or_else(|e| panic!("Cannot read {}: {}", yaml_path, e));
    let reg: Registry = serde_yaml::from_str(&raw)
        .unwrap_or_else(|e| panic!("YAML parse failed for {}: {}", yaml_path, e));

    let mut out = String::from("// AUTO-GENERATED — DO NOT EDIT\n");
    out.push_str("// Source: shared/schemas/port_registry.yaml\n\n");
    out.push_str(&format!("pub const HOST: &str = {:?};\n\n", reg.host));
    out.push_str("pub const PORTS: &[ServicePort] = &[\n");
    for s in &reg.services {
        out.push_str(&format!(
            "    ServicePort {{ name: {:?}, port: {}, group: {:?}, health_path: {:?}, env_var: {:?}, nginx_path: {:?}, optional: {} }},\n",
            s.name, s.port, s.group, s.health_path, s.env_var, s.nginx_path, s.optional,
        ));
    }
    out.push_str("];\n");

    let dest = PathBuf::from(env::var("OUT_DIR").unwrap()).join("ports.rs");
    fs::write(dest, out).unwrap();
}
