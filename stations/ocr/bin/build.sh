#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
echo "Building apple-ocr..."
swiftc -O -o apple-ocr src/ocr.swift \
    -framework Foundation \
    -framework Vision \
    -framework AppKit \
    -framework PDFKit \
    -framework Quartz
echo "Built: $(pwd)/apple-ocr"
