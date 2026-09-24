#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -d 'build/Virtua Fighter 3.app' ]]; then
    scripts/build.sh
fi
open 'build/Virtua Fighter 3.app'
