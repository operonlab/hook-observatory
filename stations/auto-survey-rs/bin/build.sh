#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo "Building get_cg_wid..."
swiftc -O -o get_cg_wid src/get_cg_wid.swift -framework Foundation -framework CoreGraphics
echo "Built: $(pwd)/get_cg_wid"
