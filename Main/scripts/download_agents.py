#!/usr/bin/env python3
"""Download the recommended Courthouse juror GGUF models from Hugging Face.

Models are listed in config/agent_sources.json and saved to models/agents/.
Each file is checked against its expected size and SHA-256; files that are
already present and correct are skipped, and interrupted downloads resume.

Usage:
    python scripts/download_agents.py            # download any missing jurors
    python scripts/download_agents.py --check    # only verify what is present
    python scripts/download_agents.py --only Hermes-3-Llama-3.2-3B-Q4_K_M.gguf

Uses only the Python standard library. Set HF_TOKEN if a repo ever requires login.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / 'config' / 'agent_sources.json'
AGENTS_DIR = ROOT / 'models' / 'agents'
CHUNK = 4 * 1024 * 1024


def load_manifest():
    data = json.loads(MANIFEST.read_text(encoding='utf-8'))
    entries = data.get('agents') or []
    for e in entries:
        name = e['file']
        if Path(name).name != name or not name.lower().endswith('.gguf'):
            raise SystemExit(f'Invalid file name in manifest: {name!r}')
    return entries


def sha256_of(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(CHUNK), b''):
            sha.update(chunk)
    return sha.hexdigest()


def is_valid(path: Path, entry) -> bool:
    return (path.is_file() and path.stat().st_size == entry['size']
            and sha256_of(path) == entry['sha256'])


def gib(n):
    return f'{n / 1024**3:.2f} GiB'


def download(entry) -> None:
    dest = AGENTS_DIR / entry['file']
    part = dest.with_name(dest.name + '.part')
    url = ('https://huggingface.co/' + entry['repo'] + '/resolve/main/'
           + urllib.parse.quote(entry['source_file']))
    have = part.stat().st_size if part.exists() else 0
    if have > entry['size']:
        part.unlink()
        have = 0
    headers = {'User-Agent': 'courthouse-agent-downloader'}
    if have:
        headers['Range'] = f'bytes={have}-'
    token = os.getenv('HF_TOKEN')
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        if have and resp.status != 206:   # server ignored the range request: start over
            have = 0
        total = entry['size']
        done = have
        last = 0.0
        with open(part, 'ab' if have else 'wb') as out:
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                now = time.monotonic()
                if now - last > 0.5:
                    last = now
                    print(f'\r  {gib(done)} / {gib(total)} ({100 * done // total}%)', end='', flush=True)
    print(f'\r  {gib(done)} / {gib(entry["size"])} (100%)   ')
    print('  Verifying SHA-256...')
    if part.stat().st_size != entry['size'] or sha256_of(part) != entry['sha256']:
        part.unlink()
        raise RuntimeError('downloaded file does not match the expected size/SHA-256 (deleted it; re-run to retry)')
    os.replace(part, dest)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--check', action='store_true', help='only verify files already in models/agents/')
    ap.add_argument('--only', nargs='+', metavar='FILE', help='limit to these manifest file names')
    args = ap.parse_args()

    entries = load_manifest()
    if args.only:
        unknown = set(args.only) - {e['file'] for e in entries}
        if unknown:
            raise SystemExit('Not in config/agent_sources.json: ' + ', '.join(sorted(unknown)))
        entries = [e for e in entries if e['file'] in args.only]
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)

    failures = 0
    for i, e in enumerate(entries, 1):
        dest = AGENTS_DIR / e['file']
        print(f'[{i}/{len(entries)}] {e["file"]}  ({gib(e["size"])}, {e["repo"]})')
        if dest.exists():
            print('  Present, verifying SHA-256...')
            if is_valid(dest, e):
                print('  OK')
                continue
            print('  MISMATCH: existing file differs from the expected model.')
            if args.check:
                failures += 1
                continue
            print('  Leaving it untouched; move or delete it, then re-run to download.')
            failures += 1
            continue
        if args.check:
            print('  MISSING')
            failures += 1
            continue
        try:
            download(e)
            print('  OK')
        except (urllib.error.URLError, OSError, RuntimeError) as exc:
            print(f'\n  FAILED: {exc}')
            failures += 1

    print()
    if failures:
        print(f'{failures} of {len(entries)} juror model(s) are missing or invalid.')
        sys.exit(1)
    print(f'All {len(entries)} juror model(s) ready in models/agents/. Start Courthouse to use them.')


if __name__ == '__main__':
    main()
