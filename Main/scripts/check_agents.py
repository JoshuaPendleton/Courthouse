#!/usr/bin/env python3
"""Show whether each hosted GGUF file is present and header-valid (no inference)."""
from pathlib import Path
import json
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'config'/'agent_models.json').read_text())
for i,agent in enumerate(manifest['agents'],1):
    path=root/'models'/'agents'/agent['file']
    exists=path.is_file()
    valid=exists and path.stat().st_size>=8 and path.open('rb').read(4)==b'GGUF'
    print(f"Agent {i}: {'GGUF found' if valid else 'MISSING/INVALID'} | {path}")
