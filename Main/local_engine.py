"""Local GGUF inference: one uploaded TARGET, N server-hosted red-team models.

Hosted agents are discovered by scanning models/agents/*.gguf (no config manifest).
They are registered and (by default) preloaded; the directory is re-scanned on
health and assessment so the live set matches the host filesystem. No scripted
attack model is used. The target model is uploaded per assessment. All tool
calls are simulated only.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import os
import re
import secrets
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = ROOT / 'models' / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DIR = UPLOAD_DIR  # Existing integration compatibility: uploaded target directory.
HOSTED_DIR = (ROOT / 'models' / 'agents').resolve()
MAX_BYTES = int(os.getenv('COURTHOUSE_MAX_MODEL_BYTES', str(8 * 1024**3)))
REGISTRY: dict[str,dict] = {}
_LOCK = threading.RLock()
_CACHE = OrderedDict()
HOSTED_AGENTS: list[dict] = []
HOSTED_STATUS: dict = {'ready': False, 'preloaded': False, 'agents': [], 'error': 'Hosted model setup has not started.'}
_HOSTED_FINGERPRINT: tuple | None = None
_PRELOAD_PREFERRED: bool | None = None


_DIGEST_CACHE: dict = {}


def _digest(path):
    # Health checks rescan models/agents every few seconds; re-hashing multi-GB weights each
    # time made /api/health take 20s+. Reuse the hash until the file's size or mtime changes.
    st = os.stat(path)
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key in _DIGEST_CACHE:
        return _DIGEST_CACHE[key]
    sha = hashlib.sha256()
    with open(path, 'rb') as inp:
        for chunk in iter(lambda: inp.read(4 * 1024 * 1024), b''):
            sha.update(chunk)
    _DIGEST_CACHE[key] = sha.hexdigest()
    return _DIGEST_CACHE[key]


def _check_gguf_file(path):
    if not path.is_file() or path.stat().st_size < 8:
        raise ValueError(f'Missing or empty GGUF file: {path.name}')
    with path.open('rb') as inp:
        if inp.read(4) != b'GGUF':
            raise ValueError(f'{path.name} is not GGUF data. Did you clone without Git LFS?')


def scan_hosted_ggufs():
    """Return validated GGUF files directly inside models/agents/, sorted by name."""
    HOSTED_DIR.mkdir(parents=True, exist_ok=True)
    found = []
    for path in sorted(HOSTED_DIR.iterdir(), key=lambda p: p.name.lower()):
        if not path.name.lower().endswith('.gguf') or path.name.startswith('.'):
            continue
        if path.name != Path(path.name).name:
            continue
        if path.is_symlink():
            raise ValueError(f'{path.name} must be a regular GGUF file inside models/agents/.')
        resolved = path.resolve()
        if resolved.parent != HOSTED_DIR or not resolved.is_file():
            raise ValueError(f'{path.name} must be inside models/agents/.')
        _check_gguf_file(resolved)
        digest = _digest(resolved)
        found.append({
            'filename': resolved.name,
            'path': resolved,
            'sha256': digest,
            'size': resolved.stat().st_size,
        })
    if found and len({x['sha256'] for x in found}) != len(found):
        raise ValueError('Hosted red-team models must use distinct GGUF weights.')
    return found


_UPLOAD_BY_SHA: dict[str, str] = {}   # sha256 -> model_id of the file kept in models/uploads
_UPLOADS_INDEXED = False


def _index_uploads():
    """Register target GGUFs already in models/uploads (e.g. from before a restart), once per process.

    The file stem becomes the model_id, so re-uploading the same weights later reuses that file
    instead of writing another copy.
    """
    global _UPLOADS_INDEXED
    if _UPLOADS_INDEXED:
        return
    found = []
    for path in sorted(UPLOAD_DIR.glob('*.gguf')):
        if path.name.startswith('.') or path.is_symlink() or not path.is_file():
            continue
        try:
            _check_gguf_file(path)
            found.append((path, _digest(path)))
        except (OSError, ValueError):
            continue
    with _LOCK:
        for path, sha in found:
            model_id = path.stem
            if sha in _UPLOAD_BY_SHA or (model_id in REGISTRY and REGISTRY[model_id].get('path') != path):
                continue
            REGISTRY[model_id] = {'model_id': model_id, 'name': path.name, 'path': path, 'sha256': sha,
                                  'size': path.stat().st_size, 'source': 'uploaded_target'}
            _UPLOAD_BY_SHA[sha] = model_id
        _UPLOADS_INDEXED = True


def save_upload(stream, length, filename):
    """Save an untrusted target GGUF without executing it; check name/size/header.

    Identical weights (same SHA-256) are stored once: a repeat upload is discarded and the
    existing file's model_id is returned.
    """
    _index_uploads()
    if not 8 <= length <= MAX_BYTES:
        raise ValueError('GGUF target file exceeds the configured limit or is too small.')
    if (not filename.lower().endswith('.gguf') or '/' in filename or '\\' in filename
            or len(filename) > 180 or filename.startswith('.')):
        raise ValueError('Only a single .gguf target file is supported.')
    model_id = secrets.token_urlsafe(18)
    path = DIR / f'{model_id}.gguf'
    digest = hashlib.sha256()
    try:
        with open(path, 'xb') as out:
            remaining = length
            first = True
            while remaining:
                buf = stream.read(min(remaining, 4 * 1024 * 1024))
                if not buf:
                    raise ValueError('Upload ended early.')
                if first:
                    if buf[:4] != b'GGUF':
                        raise ValueError('Not a GGUF file (invalid header).')
                    first = False
                out.write(buf)
                digest.update(buf)
                remaining -= len(buf)
        sha = digest.hexdigest()
        with _LOCK:
            existing = REGISTRY.get(_UPLOAD_BY_SHA.get(sha, ''))
            if existing and existing['path'].is_file():
                path.unlink(missing_ok=True)   # duplicate of weights we already hold
                return {**{k: v for k, v in existing.items() if k != 'path'}, 'name': filename, 'reused': True}
            info = {'model_id':model_id,'name':filename,'path':path,
                    'sha256':sha,'size':length,'source':'uploaded_target'}
            REGISTRY[model_id]=info
            _UPLOAD_BY_SHA[sha]=model_id
        return {k:v for k,v in info.items() if k!='path'}
    except Exception:
        path.unlink(missing_ok=True)
        raise


def get_model_info(model_id):
    if model_id not in REGISTRY:
        _index_uploads()
    return REGISTRY.get(model_id)


def _has_llama():
    try:
        import llama_cpp  # noqa: F401
        return True
    except ImportError:
        return False


def _fingerprint(scanned):
    return tuple((item['filename'], item['sha256']) for item in scanned)


def _clear_hosted_registry():
    global HOSTED_AGENTS
    for old in HOSTED_AGENTS:
        REGISTRY.pop(old['model_id'], None)
        cached = _CACHE.pop(old['model_id'], None)
        if cached is not None and hasattr(cached, 'close'):
            cached.close()
    HOSTED_AGENTS = []


def initialize_hosted_agents(config_path=None, preload=None):
    """Scan models/agents for GGUF files and optionally preload them.

    config_path is ignored (kept for call-site compatibility). Missing models leave
    the site online for diagnostics; assessments need at least one valid distinct GGUF.
    """
    global HOSTED_AGENTS, HOSTED_STATUS, _HOSTED_FINGERPRINT, _PRELOAD_PREFERRED
    preload = (os.getenv('COURTHOUSE_PRELOAD_AGENTS', '1') == '1') if preload is None else bool(preload)
    _PRELOAD_PREFERRED = preload
    with _LOCK:
        _clear_hosted_registry()
        state = {'ready': False, 'preloaded': False, 'preload_requested': preload,
                 'agents': [], 'error': '', 'inference_installed': _has_llama()}
        fingerprint = ()
        try:
            scanned = scan_hosted_ggufs()
            fingerprint = _fingerprint(scanned)
            if not scanned:
                raise ValueError('No GGUF files found in models/agents/. Place at least one .gguf file there.')
            infos = []
            for idx, item in enumerate(scanned, 1):
                filename = item['filename']
                info = {'model_id': f'courthouse-agent-{idx}',
                        'name': filename[:180],
                        'path': item['path'], 'sha256': item['sha256'], 'size': item['size'],
                        'source': 'server_hosted', 'seat': idx, 'file': filename}
                infos.append(info)
                state['agents'].append({'seat': idx, 'name': filename, 'file': filename,
                                        'status': 'validated', 'size': info['size'],
                                        'sha256_prefix': info['sha256'][:12]})
            HOSTED_AGENTS = infos
            for info in infos:
                REGISTRY[info['model_id']] = info
            if not state['inference_installed']:
                raise RuntimeError('llama-cpp-python is not installed. Run the platform setup script.')
            if preload:
                # Memory scales with N hosted weights plus the uploaded target.
                for info in infos:
                    _get_llm(info['model_id'])
                state['preloaded'] = True
            state['ready'] = True
            for agent in state['agents']:
                agent['status'] = 'loaded' if preload else 'available (loads on first request)'
        except (OSError, ValueError, KeyError, RuntimeError, ImportError, MemoryError) as exc:
            state['error'] = str(exc)
        _HOSTED_FINGERPRINT = fingerprint
        HOSTED_STATUS = state
        return _status_unlocked()


def _status_unlocked():
    return {'ready': HOSTED_STATUS['ready'],
            'preloaded': HOSTED_STATUS.get('preloaded', False),
            'preload_requested': HOSTED_STATUS.get('preload_requested', True),
            'inference_installed': HOSTED_STATUS.get('inference_installed', False),
            'error': HOSTED_STATUS.get('error', ''),
            'agents': [dict(x) for x in HOSTED_STATUS.get('agents', [])]}


def refresh_hosted_agents_if_changed(preload=None):
    """Re-scan models/agents and re-register when the file set changes."""
    global _PRELOAD_PREFERRED
    if preload is not None:
        _PRELOAD_PREFERRED = bool(preload)
    preferred = _PRELOAD_PREFERRED
    if preferred is None:
        preferred = os.getenv('COURTHOUSE_PRELOAD_AGENTS', '1') == '1'
    try:
        scanned = scan_hosted_ggufs()
        fingerprint = _fingerprint(scanned)
    except (OSError, ValueError) as exc:
        with _LOCK:
            if HOSTED_STATUS.get('error') == str(exc) and not HOSTED_STATUS.get('ready'):
                return _status_unlocked()
        return initialize_hosted_agents(preload=preferred)
    with _LOCK:
        if fingerprint == _HOSTED_FINGERPRINT and HOSTED_STATUS.get('ready'):
            return _status_unlocked()
    return initialize_hosted_agents(preload=preferred)


def hosted_status():
    return refresh_hosted_agents_if_changed()


def validate_hosted_assessment(target_id, selected=None):
    """Require one uploaded target and at least one healthy hosted agent.

    ``selected`` is an optional list of agent filenames the user switched on; when given,
    only those hosted agents take part (in their models/agents order).
    """
    refresh_hosted_agents_if_changed()
    if target_id not in REGISTRY:
        _index_uploads()
    with _LOCK:
        if not HOSTED_STATUS.get('ready') or len(HOSTED_AGENTS) < 1:
            raise ValueError('Courthouse agents are not ready: '+HOSTED_STATUS.get('error','check server model setup'))
        target = REGISTRY.get(target_id)
        if not target or target.get('source') != 'uploaded_target':
            raise ValueError('Upload the target GGUF model before running an assessment.')
        if target['sha256'] in {i['sha256'] for i in HOSTED_AGENTS}:
            raise ValueError('The target model must have different weights from all hosted red-team models.')
        if selected is None:
            return target, list(HOSTED_AGENTS)
        if not isinstance(selected, list) or not all(isinstance(x, str) for x in selected):
            raise ValueError('agents must be a list of hosted model filenames.')
        known = {i['file'] for i in HOSTED_AGENTS}
        unknown = [x for x in selected if x not in known]
        if unknown:
            raise ValueError('Unknown or removed juror model(s): ' + ', '.join(unknown[:5])
                             + '. Refresh the page to update the jury.')
        chosen = [i for i in HOSTED_AGENTS if i['file'] in set(selected)]
        if not chosen:
            raise ValueError('Switch on at least one juror to run the trial.')
        return target, chosen


def _get_llm(model_id):
    """Cache GGUF runtimes; COURTHOUSE_MAX_LOADED caps concurrent loaded models."""
    from llama_cpp import Llama
    if model_id in _CACHE:
        _CACHE.move_to_end(model_id)
        return _CACHE[model_id]
    info = get_model_info(model_id)
    if info is None:
        raise ValueError('Model is not registered; reload after restarting the server.')
    # Default 2 = the active juror + the target. Jurors run one at a time, so more cached models
    # mostly just eat RAM (on 16 GB machines 4 cached models pushed Windows into heavy paging).
    capacity = max(1, min(16, int(os.getenv('COURTHOUSE_MAX_LOADED','2'))))
    while len(_CACHE) >= capacity:
        _, old = _CACHE.popitem(last=False)
        if hasattr(old,'close'):
            old.close()
    llm = Llama(model_path=str(info['path']),
                n_ctx=int(os.getenv('COURTHOUSE_N_CTX','8192')),
                n_gpu_layers=int(os.getenv('COURTHOUSE_GPU_LAYERS','0')),
                verbose=False)
    _CACHE[model_id]=llm
    return llm


_THINK_RE = re.compile(r'<think>.*?(</think>|$)', re.S | re.I)
# Grammar-constrained JSON can cut off mid-string if the token budget is tiny.
_MIN_JSON_TOKENS = int(os.getenv('COURTHOUSE_MIN_AGENT_TOKENS', '700'))


def chat_uploaded(model_id, messages, temperature=0.6, max_tokens=500, schema=None, quick=False):
    """Generate red-team output from a hosted GGUF agent, always as a JSON object.

    Every hosted-agent call in courthouse.py expects JSON, so llama.cpp's grammar-
    constrained ``response_format`` forces a syntactically valid JSON object (this
    also keeps reasoning models from emitting <think> blocks). Any stray <think>
    text is stripped defensively before returning.
    """
    with _LOCK:
        llm = _get_llm(model_id)
        result = llm.create_chat_completion(
            messages=messages, max_tokens=int(max_tokens) if quick else max(int(max_tokens), _MIN_JSON_TOKENS),
            temperature=temperature,
            response_format={'type': 'json_object', **({'schema': schema} if schema else {})})
        content=(result.get('choices') or [{}])[0].get('message',{}).get('content')
        if not isinstance(content,str) or not content.strip():
            raise ValueError('A hosted GGUF agent produced no usable text.')
        return _THINK_RE.sub('', content).strip()


def run_local(case, model_id):
    """Probe the uploaded target with inert tools. Never execute proposed tool calls."""
    with _LOCK:
        llm=_get_llm(model_id)
        kwargs={'messages':[{'role':'system','content':case.system},
                            {'role':'user','content':case.attack}],
                'max_tokens':350,'temperature':0}
        if case.tools:
            kwargs['tools']=list(case.tools)
            kwargs['tool_choice']='auto'
        try:
            result=llm.create_chat_completion(**kwargs)
        except (TypeError, ValueError, NotImplementedError) as exc:
            if case.tools:
                raise RuntimeError('Target GGUF chat template does not support tool calls') from exc
            raise
        msg=result['choices'][0].get('message') or {}
        if not str(msg.get('content') or '').strip() and not msg.get('tool_calls'):
            raise ValueError('Defendant returned no text or tool call')
        return {'content':str(msg.get('content') or '')[:5000],
                'tool_calls':msg.get('tool_calls') or []}
