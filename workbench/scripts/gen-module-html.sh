#!/bin/sh
# Generate per-module HTML files for PWA installation.
# Each module gets its own manifest, icon, theme-color, and title
# so mobile browsers read the correct manifest at page load time.

DIST="$(dirname "$0")/../dist"

gen() {
  local module="$1" title="$2" color="$3"
  sed \
    -e "s|/v2/manifest.json|/v2/manifest-${module}.json|" \
    -e "s|/v2/icons/icon-192.svg|/v2/icons/icon-${module}-192.svg|" \
    -e "s|content=\"#1e1e2e\"|content=\"${color}\"|" \
    -e "s|<title>Workshop</title>|<title>${title}</title>|" \
    "$DIST/index.html" > "$DIST/${module}.html"
  echo "  Generated ${module}.html (${title})"
}

echo "Generating module PWA pages..."
gen memvault   "記憶金庫" "#bdd4fa"
gen intelflow  "情報研究" "#94e2d5"
echo "Done."
