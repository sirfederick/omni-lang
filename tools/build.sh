#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  echo "Este script de release solo construye el host Linux x86-64 validado." >&2
  exit 2
fi
python3 "$ROOT/tools/build_compiler.py" --output "$ROOT/bin/linux-x86_64/omni" --jobs "${OMNI_BUILD_JOBS:-2}"
"$ROOT/bin/linux-x86_64/omni" --version
