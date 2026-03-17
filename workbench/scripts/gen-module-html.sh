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

echo "Done."
