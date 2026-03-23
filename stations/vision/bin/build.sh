#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
echo "Building apple-vision..."
swiftc -O -o apple-vision src/vision.swift \
    -framework Foundation \
    -framework Vision \
    -framework AppKit
echo "Built: $(pwd)/apple-vision"
