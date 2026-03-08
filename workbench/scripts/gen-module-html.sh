#!/bin/sh
# Generate per-module HTML files for PWA installation.
# Each module gets its own manifest, icon, theme-color, and title
# so mobile browsers read the correct manifest at page load time.
# Also injects precache manifest into sw.js for instant subsequent loads.

DIST="$(dirname "$0")/../dist"

gen() {
  local module="$1" title="$2" color="$3" custom_icon="$4"
  if [ "$custom_icon" = "1" ]; then
    sed \
      -e "s|/manifest.json|/manifest-${module}.json|" \
      -e "s|/icons/icon-192.png|/icons/icon-${module}-192.png|" \
      -e "s|content=\"#1e1e2e\"|content=\"${color}\"|" \
      -e "s|<title>Workshop</title>|<title>${title}</title>|" \
      "$DIST/index.html" > "$DIST/${module}.html"
  else
    sed \
      -e "s|/manifest.json|/manifest-${module}.json|" \
      -e "s|content=\"#1e1e2e\"|content=\"${color}\"|" \
      -e "s|<title>Workshop</title>|<title>${title}</title>|" \
      "$DIST/index.html" > "$DIST/${module}.html"
  fi
  echo "  Generated ${module}.html (${title})"
}

echo "Generating module PWA pages..."
gen memvault      "記憶金庫" "#bdd4fa" 1
gen intelflow     "情報研究" "#94e2d5" 1
gen finance       "記帳理財" "#a6e3a1" 1
gen taskflow      "任務排程" "#cba6f7" 1
gen ideagraph     "靈感圖譜" "#f9e2af" 1
gen admin         "管理後台" "#a6adc8" 1
gen nodeflow      "事件流程" "#fab387" 1
gen invest        "投資追蹤" "#f38ba8" 1
gen notification  "通知管理" "#cba6f7" 1
gen briefing      "每日簡報" "#c9a962" 1

# ── Inject precache manifest into sw.js ──
echo "Injecting precache manifest into sw.js..."

# Collect critical assets for precaching:
# 1. Main JS/CSS bundles (entry points, not async chunks — those are cache-first on demand)
# 2. Module HTML pages (SPA shells for instant navigation)
# 3. Key icons (PWA install + apple-touch-icon)
# 4. Manifests
ASSETS=""

# Main entry JS/CSS (referenced in index.html <script>/<link>)
for f in $(grep -oE '/static/(js|css)/[^"]+' "$DIST/index.html"); do
  ASSETS="$ASSETS\"$f\","
done

# Module HTML pages
for html in "$DIST"/*.html; do
  name="$(basename "$html")"
  case "$name" in
    index.html|pwa-debug.html|fsm-dashboard.html) continue ;;
    *) ASSETS="$ASSETS\"/$name\"," ;;
  esac
done

# Root HTML
ASSETS="$ASSETS\"/\","

# Main manifest + module manifests
ASSETS="$ASSETS\"/manifest.json\","
for mf in "$DIST"/manifest-*.json; do
  [ -f "$mf" ] && ASSETS="$ASSETS\"/$(basename "$mf")\","
done

# Key icons (192px SVG for each module + main)
ASSETS="$ASSETS\"/icons/icon-192.svg\","
for icon in "$DIST"/icons/icon-*-192.svg; do
  [ -f "$icon" ] && ASSETS="$ASSETS\"/icons/$(basename "$icon")\","
done

# Remove trailing comma, wrap in array
ASSETS="[${ASSETS%,}]"

# Replace placeholder in sw.js
sed -i '' "s|\"__PRECACHE_ASSETS__\"|${ASSETS}|g" "$DIST/sw.js"

ASSET_COUNT=$(echo "$ASSETS" | tr ',' '\n' | wc -l | tr -d ' ')
echo "  Precached ${ASSET_COUNT} assets in sw.js"
echo "Done."
