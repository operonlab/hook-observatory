# workshop-apps.inc — V2 Workshop station reverse proxy configs
# Manually maintained. All stations under /apps/.
# Auth: /_v2_auth_check (defined in main server block) → 401 → @auth_redirect → /login

# --- five-layer architecture doc (static, PUBLIC — no auth) ---
location = /apps/five-layer { return 301 /apps/five-layer/; }

location /apps/five-layer/ {
    alias /Users/joneshong/workshop/docs/architecture/five-layer/;
    index index.html;
    add_header Cache-Control "no-store" always;
}

# --- tv-pick (TV purchase persuasion page, PUBLIC — no auth) ---
location = /apps/tv-pick { return 301 /apps/tv-pick/; }

location /apps/tv-pick/ {
    alias /Users/joneshong/workshop/outputs/smart-search/tv-persuasion/public/;
    index index.html;
    add_header Cache-Control "no-store" always;
}

# --- agent-vista (proxy + websocket, PUBLIC — no auth) ---
location = /apps/vista { return 301 /apps/vista/; }

location /apps/vista/ {
    proxy_pass http://127.0.0.1:10207/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_buffering off;
    add_header Cache-Control "no-store" always;
}

# --- filebrowser (file manager, AUTH) ---
# NOTE: filebrowser must be reconfigured with --baseurl /apps/files/
location = /apps/files { return 301 /apps/files/; }

location /apps/files/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    proxy_pass http://127.0.0.1:8850/apps/files/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_buffering off;
    client_max_body_size 0;
    add_header Cache-Control "no-store" always;
}

# --- mlt-editor (proxy, AUTH) ---
location = /apps/mlt-editor { return 301 /apps/mlt-editor/; }

location /apps/mlt-editor/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=global burst=100 nodelay;
    proxy_pass http://127.0.0.1:10206/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_buffering off;
    add_header Cache-Control "no-store" always;
}

# --- session-channel (proxy + SSE, AUTH) ---
location = /apps/channel { return 301 /apps/channel/; }

location /apps/channel/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=global burst=100 nodelay;
    proxy_pass http://127.0.0.1:10101/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 86400s;
    proxy_send_timeout 86400s;
    chunked_transfer_encoding on;
    add_header Cache-Control "no-store" always;
}

# hook-observatory (/apps/hook/ → 127.0.0.1:10100) removed 2026-05-13 —
# Python FastAPI dashboard archived; session-channel dashboard takes over
# observability. If you still have an active Nginx config on the host that
# references this path, run `nginx -t` then reload after this file syncs.

# --- tmux-webui (proxy + websocket, AUTH) ---
location = /apps/tmux { return 301 /apps/tmux/; }

location /apps/tmux/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=global burst=100 nodelay;
    proxy_pass http://127.0.0.1:10105/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_buffering off;
    client_max_body_size 50m;
    add_header Cache-Control "no-store" always;
}

# --- system-monitor (API + dashboard, AUTH) ---
location = /apps/sysmon { return 301 /apps/sysmon/; }

location /apps/sysmon/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=global burst=100 nodelay;
    proxy_pass http://127.0.0.1:10102/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_buffering off;
    add_header Cache-Control "no-store" always;
}

# --- sentinel (status page, AUTH) ---
location = /apps/sentinel { return 301 /apps/sentinel/; }

# PWA assets bypass auth (manifest, sw, icons) — browser fetches these
# without cookies, so auth_request would 302 → /login HTML and the parser
# would see "<" as JSON line:1 col:1 → "Manifest: Syntax error".
location ~ ^/apps/sentinel/(sw\.js|static/(manifest\.json|icons/[^/]*))$ {
    rewrite ^/apps/sentinel/(.*) /$1 break;
    proxy_pass http://127.0.0.1:4101;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    add_header Cache-Control "no-store" always;
}

location /apps/sentinel/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=global burst=100 nodelay;
    proxy_pass http://127.0.0.1:4101/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_buffering off;
    add_header Cache-Control "no-store" always;
}

# --- auto-survey (form filler dashboard, AUTH) ---
location = /apps/survey { return 301 /apps/survey/; }

# PWA assets bypass auth (manifest, sw, icons)
location ~ ^/apps/survey/(sw\.js|static/(manifest\.json|icon[^/]*))$ {
    rewrite ^/apps/survey/(.*) /$1 break;
    proxy_pass http://127.0.0.1:10300;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    add_header Cache-Control "no-store" always;
}

location /apps/survey/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=global burst=100 nodelay;
    proxy_pass http://127.0.0.1:10300/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_buffering off;
    add_header Cache-Control "no-store" always;
}

# --- ntfy (push notification server, PUBLIC — ntfy app needs direct access) ---
location /ntfy/ {
    proxy_pass http://127.0.0.1:9080/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    # WebSocket + SSE for real-time push delivery
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 600s;
    chunked_transfer_encoding on;
}

# --- bark (iPhone push server, PUBLIC — Bark app needs direct access) ---
location /bark/ {
    proxy_pass http://127.0.0.1:8090/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_buffering off;
}

# --- agent-metrics (API + dashboard, AUTH) ---
location = /apps/agent-metrics { return 301 /apps/agent-metrics/; }

location /apps/agent-metrics/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=global burst=100 nodelay;
    proxy_pass http://127.0.0.1:10103/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_buffering off;
    add_header Cache-Control "no-store" always;
}

# --- anvil (skill data platform, AUTH) ---
location = /apps/anvil { return 301 /apps/anvil/; }

location /apps/capture-console/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=global burst=100 nodelay;
    proxy_pass http://127.0.0.1:10104/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_buffering off;
    add_header Cache-Control "no-store" always;
}

location /apps/anvil/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=global burst=100 nodelay;
    proxy_pass http://127.0.0.1:10301/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_buffering off;
    add_header Cache-Control "no-store" always;
}

# --- voice-gateway (Voice VAD+KWS, AUTH + SSE) ---
location = /apps/voice { return 301 /apps/voice/; }

location /apps/voice/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=global burst=100 nodelay;
    proxy_pass http://127.0.0.1:10204/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 86400s;
    proxy_send_timeout 86400s;
    chunked_transfer_encoding on;
    add_header Cache-Control "no-store" always;
}

# --- stt (redirects to voice center) ---
location /apps/stt/ { return 301 /apps/voice/; }

# --- ocr (Text Extraction, AUTH) ---
location /apps/ocr/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=global burst=100 nodelay;
    proxy_pass http://127.0.0.1:10202/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_buffering off;
    add_header Cache-Control "no-store" always;
}

# --- cronicle (scheduler Web UI + WebSocket, AUTH) ---
location = /apps/scheduler { return 301 /apps/scheduler/; }

# PWA static files — exempt from auth, permissive rate limit (prevents 429 on manifest fetch)
location ~ ^/apps/scheduler/(manifest\.json|sw\.js|images/icon-.*\.png)$ {
    limit_req zone=static burst=50 nodelay;
    proxy_pass http://127.0.0.1:4105/$1;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    add_header Cache-Control "no-store" always;
}

location /apps/scheduler/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=global burst=100 nodelay;
    proxy_pass http://127.0.0.1:4105/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_buffering off;
    add_header Cache-Control "no-store" always;
}

# Cronicle API — JS runtime uses absolute /api/app/* and /api/user/* paths
location ^~ /api/app/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=static burst=50 nodelay;
    proxy_pass http://127.0.0.1:4105/api/app/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
}

location ^~ /api/user/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=static burst=50 nodelay;
    proxy_pass http://127.0.0.1:4105/api/user/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
}

# Cronicle WebSocket — socket.io for real-time job updates
# No auth_request: WS upgrade handshake doesn't reliably carry cookies;
# access already gated by the /apps/scheduler/ auth check.
location /socket.io/ {
    limit_req zone=static burst=50 nodelay;
    proxy_pass http://127.0.0.1:4105/socket.io/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_read_timeout 86400s;
    proxy_send_timeout 86400s;
}

# Anvil station API proxy (for workbench frontend)
location /api/anvil/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=global burst=100 nodelay;
    proxy_pass http://127.0.0.1:10301/api/anvil/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
}

# --- omlx (local LLM server + admin GUI, AUTH) ---
# oMLX hardcodes /admin/* absolute paths in HTML/JS.
# sub_filter rewrites /admin/ → /omlx/ so all assets/API/redirects work.
# oMLX Chat UI calls /v1/* (OpenAI-compatible API) with absolute paths
location /v1/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    proxy_pass http://127.0.0.1:8899/v1/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_buffering off;
    proxy_read_timeout 300s;
}

location = /omlx { return 301 /omlx/; }

location /omlx/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=global burst=100 nodelay;
    proxy_pass http://127.0.0.1:8899/admin/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header Accept-Encoding "";
    proxy_buffering off;
    proxy_read_timeout 300s;

    # Rewrite redirect Location headers: /admin/* → /omlx/*
    proxy_redirect /admin/ /omlx/;

    # Rewrite Set-Cookie path so oMLX session cookie works under /omlx/
    proxy_cookie_path /admin/ /omlx/;

    sub_filter_once off;
    sub_filter_types application/javascript text/css;
    sub_filter '/admin/' '/omlx/';
    sub_filter '"/admin/' '"/omlx/';
    sub_filter "'/admin/" "'/omlx/";

    add_header Cache-Control "no-store" always;
}

# --- dev-blog (Astro SSR BUILT preview on 4118, AUTH) ---
# Uses built server (not Vite dev) so compiled JS has standard paths that sub_filter can rewrite.
location = /apps/dev-blog { return 301 /apps/dev-blog/; }

location /apps/dev-blog/_astro/ {
    # Static assets — served directly, rewrite prefix
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    proxy_pass http://127.0.0.1:10302/_astro/;
    add_header Cache-Control "no-store" always;
}

location /apps/dev-blog/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=global burst=100 nodelay;
    proxy_pass http://127.0.0.1:10302/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Accept-Encoding "";

    # Rewrite absolute paths in HTML so links + Astro islands work under /apps/dev-blog/
    sub_filter_once off;
    sub_filter_types text/html;
    sub_filter 'href="/' 'href="/apps/dev-blog/';
    sub_filter 'src="/' 'src="/apps/dev-blog/';
    sub_filter 'action="/' 'action="/apps/dev-blog/';
    sub_filter 'component-url="/' 'component-url="/apps/dev-blog/';
    sub_filter 'renderer-url="/' 'renderer-url="/apps/dev-blog/';
    sub_filter 'before-hydration-url="/' 'before-hydration-url="/apps/dev-blog/';
    sub_filter 'import("/' 'import("/apps/dev-blog/';

    # Rewrite redirect Location headers (302 from Astro SSR)
    proxy_redirect / /apps/dev-blog/;

    add_header Cache-Control "no-store" always;
}
