# Nginx config (source of truth)

Workshop's reverse proxy lives at `/opt/homebrew/etc/nginx/conf.d/workshop-apps.inc`.
This directory is the version-controlled mirror.

## Deploy

```bash
cp infra/nginx/workshop-apps.inc /opt/homebrew/etc/nginx/conf.d/workshop-apps.inc
nginx -t && nginx -s reload
```

## PWA bypass pattern

Stations that ship a PWA (manifest + service worker) MUST add a bypass
location before the auth-protected `location /apps/<name>/` block, otherwise
the browser's cookie-less manifest fetch hits `auth_request`, gets a 302 to
`/login`, parses the HTML as JSON and fails with
`Manifest: Line: 1, column: 1, Syntax error`.

```nginx
location ~ ^/apps/<name>/(sw\.js|static/(manifest\.json|icons/[^/]*))$ {
    rewrite ^/apps/<name>/(.*) /$1 break;
    proxy_pass http://127.0.0.1:<port>;
    add_header Cache-Control "no-store" always;
}
```

Currently applied to: `apps/survey`, `apps/sentinel`.
