#!/usr/bin/env sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python server.py
fi
echo 'No .venv found; run ./install_dependencies.sh first.' >&2
exec "${PYTHON:-python3}" server.py
