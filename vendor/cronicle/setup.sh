#!/bin/bash
# Re-install Cronicle from source
# Run this if node_modules is missing (e.g., fresh clone)
set -e
cd "$(dirname "$0")"

echo "Installing Cronicle dependencies..."
npm install --production

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

echo ""
echo "Done! Start with: bash bin/control.sh start"
echo "Web UI: http://127.0.0.1:4105/"
