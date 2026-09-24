#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build/icon
xcrun swiftc -O -target arm64-apple-macosx14.0 -framework AppKit scripts/build_icon.swift -o build/icon/draw-icon
build/icon/draw-icon build/icon/AppIcon.iconset
/usr/bin/iconutil --convert icns build/icon/AppIcon.iconset --output build/icon/AppIcon.icns
cp build/icon/AppIcon.iconset/icon_512x512@2x.png build/icon/AppIcon.png
