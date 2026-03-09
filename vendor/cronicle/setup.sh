#!/bin/bash
# Re-install Cronicle Edge from source
# Run this if node_modules is missing (e.g., fresh clone)
set -e
cd "$(dirname "$0")"

echo "Installing Cronicle Edge dependencies..."
npm install

echo "Setting up data directory..."
mkdir -p logs queue
mkdir -p /Users/joneshong/workshop/data/cronicle

# Only run storage setup if data dir is empty
if [ ! -d "/Users/joneshong/workshop/data/cronicle/global" ]; then
    echo "Initializing Cronicle storage..."
    node bin/storage-cli.js setup
    echo "Storage initialized. Default admin password: admin"
else
    echo "Storage already initialized, skipping setup."
fi

echo "Building frontend assets..."
export PATH="./node_modules/.bin:$PATH"

# Copy JS externals
mkdir -p htdocs/js/external
/bin/cp \
  node_modules/jquery/dist/jquery.min.js \
  node_modules/moment/min/moment.min.js \
  node_modules/moment-timezone/builds/moment-timezone-with-data.min.js \
  node_modules/chart.js/dist/Chart.min.js \
  node_modules/jstimezonedetect/dist/jstz.min.js \
  node_modules/socket.io/client-dist/socket.io.min.js \
  node_modules/ansi_up/ansi_up.js \
  node_modules/jquery-ui-dist/jquery-ui.min.js \
  node_modules/graphlib/dist/graphlib.min.js \
  node_modules/vis-network/dist/vis-network.min.js \
  node_modules/xss/dist/xss.min.js \
  node_modules/jquery-datetimepicker/build/jquery.datetimepicker.full.min.js \
  node_modules/diff/dist/diff.min.js \
  node_modules/@xterm/xterm/lib/xterm.js \
  htdocs/js/external/

# Copy CSS
/bin/cp \
  node_modules/font-awesome/css/font-awesome.min.css \
  node_modules/@mdi/font/css/materialdesignicons.min.css \
  node_modules/jquery-ui-dist/jquery-ui.min.css \
  node_modules/jquery-datetimepicker/build/jquery.datetimepicker.min.css \
  node_modules/pixl-webapp/css/base.css \
  node_modules/@xterm/xterm/css/xterm.css \
  htdocs/css/

# Copy fonts
mkdir -p htdocs/fonts
/bin/cp \
  node_modules/font-awesome/fonts/*.woff2 \
  node_modules/@mdi/font/fonts/*.woff2 \
  node_modules/pixl-webapp/fonts/*.woff2 \
  htdocs/fonts/

# Bundle codemirror CSS
/bin/cat \
  node_modules/codemirror/lib/codemirror.css \
  node_modules/codemirror/theme/darcula.css \
  node_modules/codemirror/theme/solarized.css \
  node_modules/codemirror/theme/gruvbox-dark.css \
  node_modules/codemirror/theme/base16-dark.css \
  node_modules/codemirror/theme/ambiance.css \
  node_modules/codemirror/theme/nord.css \
  node_modules/codemirror/addon/scroll/simplescrollbars.css \
  node_modules/codemirror/addon/display/fullscreen.css \
  node_modules/codemirror/addon/lint/lint.css \
  node_modules/codemirror/addon/fold/foldgutter.css \
  > htdocs/css/codemirror.css

# Bundle codemirror JS
/bin/cat \
  node_modules/codemirror/lib/codemirror.js \
  node_modules/codemirror/addon/scroll/simplescrollbars.js \
  node_modules/codemirror/addon/edit/matchbrackets.js \
  node_modules/codemirror/addon/selection/active-line.js \
  node_modules/codemirror/addon/fold/foldgutter.js \
  node_modules/codemirror/addon/fold/foldcode.js \
  node_modules/codemirror/addon/fold/brace-fold.js \
  node_modules/codemirror/addon/fold/indent-fold.js \
  node_modules/codemirror/mode/powershell/powershell.js \
  node_modules/codemirror/mode/javascript/javascript.js \
  node_modules/codemirror/mode/python/python.js \
  node_modules/codemirror/mode/perl/perl.js \
  node_modules/codemirror/mode/shell/shell.js \
  node_modules/codemirror/mode/groovy/groovy.js \
  node_modules/codemirror/mode/clike/clike.js \
  node_modules/codemirror/mode/properties/properties.js \
  node_modules/codemirror/addon/display/fullscreen.js \
  node_modules/codemirror/addon/display/placeholder.js \
  node_modules/codemirror/mode/xml/xml.js \
  node_modules/codemirror/mode/sql/sql.js \
  node_modules/js-yaml/dist/js-yaml.js \
  node_modules/codemirror/addon/lint/lint.js \
  node_modules/codemirror/addon/lint/json-lint.js \
  node_modules/codemirror/addon/lint/yaml-lint.js \
  node_modules/codemirror/addon/mode/simple.js \
  node_modules/codemirror/mode/dockerfile/dockerfile.js \
  node_modules/codemirror/mode/toml/toml.js \
  node_modules/codemirror/mode/yaml/yaml.js \
  node_modules/codemirror/addon/comment/comment.js \
  node_modules/jsonlint-mod/lib/jsonlint.js \
  | esbuild --minify=true > htdocs/js/codemirror.min.js

# Bundle pixl-webapp common
/bin/cat \
  node_modules/pixl-webapp/js/md5.js \
  node_modules/pixl-webapp/js/oop.js \
  node_modules/pixl-webapp/js/xml.js \
  node_modules/pixl-webapp/js/tools.js \
  node_modules/pixl-webapp/js/datetime.js \
  node_modules/pixl-webapp/js/page.js \
  node_modules/pixl-webapp/js/dialog.js \
  node_modules/pixl-webapp/js/base.js \
  | esbuild --minify=true --keep-names > htdocs/js/common.min.js

# Bundle app JS
/bin/cat htdocs/js/app.js \
  htdocs/js/pages/Base.class.js \
  htdocs/js/pages/Home.class.js \
  htdocs/js/pages/Login.class.js \
  htdocs/js/pages/Schedule.class.js \
  htdocs/js/pages/History.class.js \
  htdocs/js/pages/JobDetails.class.js \
  htdocs/js/pages/MyAccount.class.js \
  htdocs/js/pages/Admin.class.js \
  htdocs/js/pages/admin/Categories.js \
  htdocs/js/pages/admin/Servers.js \
  htdocs/js/pages/admin/Users.js \
  htdocs/js/pages/admin/Plugins.js \
  htdocs/js/pages/admin/Activity.js \
  htdocs/js/pages/admin/APIKeys.js \
  htdocs/js/pages/admin/ConfigKeys.js \
  htdocs/js/pages/admin/Secrets.js \
  | esbuild --minify=true --keep-names > htdocs/js/combo.min.js

# Set index.html
/bin/cp htdocs/index-bundle.html htdocs/index.html

echo ""
echo "Done! Start with: bash bin/control.sh start"
echo "Web UI: http://127.0.0.1:4105/"
