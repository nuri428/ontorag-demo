#!/usr/bin/env bash
# Clone sibling framework repos next to ontorag-demo if they are missing.
# Expected layout:
#   <parent>/
#   ├── ontorag/
#   ├── ontorag-flow/
#   └── ontorag-demo/   <- this repo
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARENT="$(dirname "$ROOT")"

clone_if_missing() {
    local name="$1" url="$2"
    local dest="$PARENT/$name"
    if [ -e "$dest" ]; then
        echo "ok: $dest already exists"
    else
        echo "cloning $url -> $dest"
        git clone "$url" "$dest"
    fi
}

clone_if_missing ontorag      https://github.com/nuri428/ontorag.git
clone_if_missing ontorag-flow https://github.com/nuri428/ontorag-flow.git

echo "done. next: uv sync --extra dev"
