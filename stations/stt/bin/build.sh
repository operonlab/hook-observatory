#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
echo "Building apple-stt..."
swiftc -O -o apple-stt src/stt.swift \
    -framework Foundation \
    -framework Speech
echo "Built: $(pwd)/apple-stt"
