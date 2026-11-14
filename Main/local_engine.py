"""Local GGUF inference: one uploaded TARGET, three server-hosted red-team models.

Hosted agent files are configured in config/agent_models.json. They are registered
and (by default) preloaded at server startup. No scripted attack model is used.
The target model is uploaded per assessment. All tool calls are simulated only.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import os
import secrets
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = ROOT / 'models' / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DIR = UPLOAD_DIR  # Existing integration compatibility: uploaded target directory.
CONFIG_FILE = ROOT / 'config' / 'agent_models.json'
HOSTED_DIR = (ROOT / 'models' / 'agents').resolve()
MAX_BYTES = int(os.getenv('COURTHOUSE_MAX_MODEL_BYTES', str(8 * 1024**3)))
REGISTRY: dict[str,dict] = {}
_LOCK = threading.RLock()
_CACHE = OrderedDict()
HOSTED_AGENTS: list[dict] = []
HOSTED_STATUS: dict = {'ready': False, 'preloaded': False, 'agents': [], 'error': 'Hosted model setup has not started.'}


def _digest(path):
    sha = hashlib.sha256()
    with open(path, 'rb') as inp:
        for chunk in iter(lambda: inp.read(4 * 1024 * 1024), b''):
            sha.update(chunk)
    return sha.hexdigest()


def _check_gguf_file(path):
    if not path.is_file() or path.stat().st_size < 8:
        raise ValueError(f'Missing or empty GGUF file: {path.name}')
    with path.open('rb') as inp:
        if inp.read(4) != b'GGUF':
            raise ValueError(f'{path.name} is not GGUF data. Did you clone without Git LFS?')


def save_upload(stream, length, filename):
    """Save an untrusted target GGUF without executing it; check name/size/header."""
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
        info = {'model_id':model_id,'name':filename,'path':path,
                'sha256':digest.hexdigest(),'size':length,'source':'uploaded_target'}
        with _LOCK:
            REGISTRY[model_id]=info
        return {k:v for k,v in info.items() if k!='path'}
    except Exception:
        path.unlink(missing_ok=True)
        raise


def get_model_info(model_id):
    return REGISTRY.get(model_id)


def _has_llama():
    try:
        import llama_cpp  # noqa: F401
        return True
    except ImportError:
        return False


def initialize_hosted_agents(config_path=None, preload=None):
    """Register configured models and optionally load all three into inference RAM.

    Does not silently substitute scripted agents. Missing models leave site online
    for diagnostics but assessments unavailable until corrected and server restarted.
    """
    global HOSTED_AGENTS, HOSTED_STATUS
    config_path = Path(config_path or os.getenv('COURTHOUSE_AGENTS_CONFIG', CONFIG_FILE)).resolve()
    preload = (os.getenv('COURTHOUSE_PRELOAD_AGENTS','1') == '1') if preload is None else bool(preload)
    with _LOCK:
        # Clear previously registered hosted agents, never delete user-uploaded targets.
        for old in HOSTED_AGENTS:
            REGISTRY.pop(old['model_id'], None)
            cached = _CACHE.pop(old['model_id'], None)
            if cached is not None and hasattr(cached,'close'):
                cached.close()
        HOSTED_AGENTS = []
        state = {'ready':False, 'preloaded':False, 'preload_requested':preload,
                 'agents':[], 'error':'', 'inference_installed':_has_llama()}
        try:
            config = json.loads(config_path.read_text(encoding='utf-8'))
            models = config.get('agents')
            if not isinstance(models,list) or len(models)!=3:
                raise ValueError('config/agent_models.json must define exactly three agents.')
            infos=[]
            for idx, spec in enumerate(models,1):
                # Safe, fixed directory: paths cannot escape models/agents.
                filename=spec.get('file')
                if (not isinstance(filename,str) or not filename.endswith('.gguf') or
                    Path(filename).name != filename or filename.startswith('.')):
                    raise ValueError(f'Agent {idx} must name a .gguf file inside models/agents/.')
                file=(HOSTED_DIR / filename).resolve()
                if file.parent != HOSTED_DIR:
                    raise ValueError(f'Agent {idx} file must be inside models/agents/.')
                _check_gguf_file(file)
                info={'model_id':f'courthouse-agent-{idx}',
                      'name':str(spec.get('name') or f'Courthouse Agent {idx}')[:120],
                      'path':file,'sha256':_digest(file),'size':file.stat().st_size,
                      'source':'server_hosted','seat':idx}
                infos.append(info)
                state['agents'].append({'seat':idx,'name':info['name'],'file':filename,
                                        'status':'validated','size':info['size'],
                                        'sha256_prefix':info['sha256'][:12]})
            if len({x['sha256'] for x in infos}) != 3:
                raise ValueError('The three server-hosted red-team models must use distinct GGUF weights.')
            HOSTED_AGENTS=infos
            for info in infos:
                REGISTRY[info['model_id']]=info
            if not state['inference_installed']:
                raise RuntimeError('llama-cpp-python is not installed. Run the platform setup script.')
            if preload:
                # Deliberately load all three: memory requirement >= sum of agent weights.
                for info in infos:
                    _get_llm(info['model_id'])
                state['preloaded']=True
            state['ready']=True
            for agent in state['agents']:
                agent['status']='loaded' if preload else 'available (loads on first request)'
        except (OSError, ValueError, KeyError, RuntimeError, ImportError, MemoryError) as exc:
            state['error']=str(exc)
            # If a preload fails halfway, no assessment can run (report error accurately).
        HOSTED_STATUS=state
        return hosted_status()


def hosted_status():
    with _LOCK:
        return {'ready':HOSTED_STATUS['ready'],
                'preloaded':HOSTED_STATUS.get('preloaded',False),
                'preload_requested':HOSTED_STATUS.get('preload_requested',True),
                'inference_installed':HOSTED_STATUS.get('inference_installed',False),
                'error':HOSTED_STATUS.get('error',''),
                'agents':[dict(x) for x in HOSTED_STATUS.get('agents',[])]}


def validate_hosted_assessment(target_id):
    """Require one uploaded target and a healthy hosted three-agent runtime."""
    with _LOCK:
        if not HOSTED_STATUS.get('ready') or len(HOSTED_AGENTS)!=3:
            raise ValueError('Courthouse agents are not ready: '+HOSTED_STATUS.get('error','check server model setup'))
        target = REGISTRY.get(target_id)
        if not target or target.get('source') != 'uploaded_target':
            raise ValueError('Upload the target GGUF model before running an assessment.')
        if target['sha256'] in {i['sha256'] for i in HOSTED_AGENTS}:
            raise ValueError('The target model must have different weights from all hosted red-team models.')
        return target, list(HOSTED_AGENTS)


def _get_llm(model_id):
    """Cache GGUF runtimes; by default all three agents + current target stay in RAM."""
    from llama_cpp import Llama
    if model_id in _CACHE:
        _CACHE.move_to_end(model_id)
        return _CACHE[model_id]
    info = get_model_info(model_id)
    if info is None:
        raise ValueError('Model is not registered; reload after restarting the server.')
    capacity = max(1, min(16, int(os.getenv('COURTHOUSE_MAX_LOADED','4'))))
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


def chat_uploaded(model_id, messages, temperature=0.6, max_tokens=500):
    """Generate genuine AI red-team text from the corresponding hosted GGUF model."""
    with _LOCK:
        result = _get_llm(model_id).create_chat_completion(
            messages=messages, max_tokens=max_tokens, temperature=temperature)
        content=(result.get('choices') or [{}])[0].get('message',{}).get('content')
        if not isinstance(content,str) or not content.strip():
            raise ValueError('A hosted GGUF agent produced no usable text.')
        return content


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
        return {'content':str(msg.get('content') or '')[:5000],
                'tool_calls':msg.get('tool_calls') or []}
