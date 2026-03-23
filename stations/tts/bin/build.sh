#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
echo "Building apple-tts..."
swiftc -O -o apple-tts src/tts.swift \
    -framework Foundation \
    -framework AVFoundation \
    -framework AppKit
echo "Built: $(pwd)/apple-tts"
