/// 1:1 port of stations/sentinel/prompt_templates.py

pub const SYSTEM_CONTEXT: &str = r#"You are a Workshop infrastructure repair agent.
Your job is to diagnose and fix the failed service.
- Work in /Users/joneshong/workshop/
- Check logs at /opt/homebrew/var/log/workshop/{service}/
- Use workshop-services.sh for service management
- Do NOT modify application code — only restart/rebuild/reconfigure
- Report what you found and what you did"#;

pub const GENERIC_TEMPLATE: &str = r#"Service '{service}' is unhealthy.
Failure: {detail}

Steps:
1. Check if the process is running
2. Check logs in /opt/homebrew/var/log/workshop/{service}/
3. Try restarting via workshop-services.sh
4. Verify the health endpoint
"#;

fn template_for(service: &str) -> &'static str {
    match service {
        "core" => r#"Service 'core' (port 10000) is unhealthy.
Failure: {detail}

Steps:
1. Check logs: tail -50 /opt/homebrew/var/log/workshop/core/$(date +%Y-%m-%d).log
2. Check if process is running: lsof -i :10000
3. Try restart: /Users/joneshong/workshop/scripts/workshop-services.sh restart core
4. Verify: curl -s http://127.0.0.1:10000/health
"#,
        "frontend" => r#"Frontend (Nginx serving /) is unhealthy.
Failure: {detail}

Steps:
1. Check nginx: nginx -t
2. Check if dist exists: ls -la /Users/joneshong/workshop/workbench/dist/index.html
3. If dist missing or broken, rebuild:
   cd /Users/joneshong/workshop/workbench && pnpm run build
4. Reload nginx: nginx -s reload
5. Verify: curl -s http://127.0.0.1/ | head -5
"#,
        // hook-observatory removed 2026-05-13 — Python dashboard archived; no
        // listen port. If sentinel still routes a check there it should be a
        // configuration leftover; remove the registry entry.
        "postgres" => r#"PostgreSQL container is unhealthy.
Failure: {detail}

Steps:
1. Check container: docker ps -a | grep postgres
2. Check logs: docker logs ws-infra-postgres-1 --tail 50
3. Restart: docker restart ws-infra-postgres-1
4. Wait 5s, verify: docker exec ws-infra-postgres-1 pg_isready
"#,
        "redis" => r#"Redis container is unhealthy.
Failure: {detail}

Steps:
1. Check container: docker ps -a | grep redis
2. Check logs: docker logs ws-infra-redis-1 --tail 50
3. Restart: docker restart ws-infra-redis-1
4. Verify: docker exec ws-infra-redis-1 redis-cli ping
"#,
        "rustfs" => r#"RustFS (MinIO fork, port 9000) is unhealthy.
Failure: {detail}

Steps:
1. Check container: docker ps -a | grep rustfs
2. Restart: docker restart ws-infra-rustfs-1
3. Verify: curl -s http://127.0.0.1:9000/
"#,
        _ => GENERIC_TEMPLATE,
    }
}

pub fn build_repair_prompt(service: &str, detail: &str) -> String {
    let tmpl = template_for(service);
    let body = tmpl
        .replace("{service}", service)
        .replace("{detail}", detail);
    format!("{}\n\n{}", SYSTEM_CONTEXT, body)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_core_prompt() {
        let p = build_repair_prompt("core", "HTTP 500");
        assert!(p.contains("Workshop infrastructure repair agent"));
        assert!(p.contains("port 10000"));
        assert!(p.contains("HTTP 500"));
    }

    #[test]
    fn generic_template_for_unknown() {
        let p = build_repair_prompt("unknown-svc", "timed out");
        assert!(p.contains("'unknown-svc'"));
        assert!(p.contains("timed out"));
    }
}
