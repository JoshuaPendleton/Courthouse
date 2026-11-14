#!/usr/bin/env sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
"${PYTHON:-python3}" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-inference.txt
printf '\nSetup complete. Place agent1.gguf, agent2.gguf, agent3.gguf in models/agents.\n'
