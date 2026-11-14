#!/usr/bin/env python3
"""Show whether each hosted GGUF file is present and header-valid (no inference)."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
agents_dir = root / 'models' / 'agents'
files = sorted(
    (p for p in agents_dir.iterdir() if p.is_file() and p.name.lower().endswith('.gguf') and not p.name.startswith('.')),
    key=lambda p: p.name.lower(),
) if agents_dir.is_dir() else []
if not files:
    print(f'No .gguf files in {agents_dir}')
else:
    for i, path in enumerate(files, 1):
        valid = path.stat().st_size >= 8 and path.open('rb').read(4) == b'GGUF'
        print(f"Agent {i}: {'GGUF found' if valid else 'INVALID'} | {path.name} | {path}")
