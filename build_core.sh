#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cmake -S "$ROOT/native" -B "$ROOT/native/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$ROOT/native/build" -j"$(nproc)"
echo "StellarDustCore compilé : $ROOT/native/build/stardust-core"
