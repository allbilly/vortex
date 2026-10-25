#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
stage="${1:-quick}"
if [[ $# -gt 0 ]]; then shift; fi
case "$stage" in preflight|build|identity|memory|quick|full) ;; *) echo "usage: bash ci/mac_vortex.sh preflight|build|identity|memory|quick|full [options]" >&2; exit 2;; esac
py="${VORTEX_PYTHON:-python3}"
out="${VORTEX_MAC_OUT:-$root/build/mac-vortex-$(date -u +%Y%m%dT%H%M%SZ)-$stage-$$}"
export PYTHONDONTWRITEBYTECODE=1
exec "$py" "$root/ci/ypcb_macos.py" "$stage" --out "$out" "$@"
