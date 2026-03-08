#!/bin/bash
# Add Anvil API proxy rule to Nginx
# This allows workbench frontend to call /api/anvil/ which routes to the Anvil station

NGINX_CONF="/opt/homebrew/etc/nginx/conf.d/workshop-apps.inc"

# Check if rule already exists
if grep -q "location /api/anvil/" "$NGINX_CONF" 2>/dev/null; then
    echo "Anvil API proxy rule already exists in $NGINX_CONF"
    exit 0
fi

cat >> "$NGINX_CONF" << 'EOF'

# Anvil station API proxy (for workbench frontend)
location /api/anvil/ {
    auth_request /_v2_auth_check;
    error_page 401 = @auth_redirect;
    limit_req zone=global burst=100 nodelay;
    proxy_pass http://127.0.0.1:4103/api/anvil/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
EOF

echo "Added Anvil API proxy rule to $NGINX_CONF"
echo "Reload nginx: sudo nginx -t && sudo nginx -s reload"
