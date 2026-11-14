#!/usr/bin/env python3
"""Courthouse: cross-platform local web app; hosted red-team LLMs + uploaded target."""
from __future__ import annotations
import http.server
import json
import os
import socketserver
import threading
import urllib.parse
from pathlib import Path
from courthouse import (assess_stream, now, ATTACK_SCHEMA, INDIVIDUAL_SCHEMA, MESSAGE_SCHEMA,
                        SUMMARY_SCHEMA, VERDICT_SCHEMA, VERDICT_MODES)
from local_engine import (save_upload, validate_hosted_assessment, initialize_hosted_agents,
                          hosted_status, run_local, chat_uploaded, MAX_BYTES)

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / 'static'
HOST = os.getenv('COURTHOUSE_HOST', '127.0.0.1')
PORT = int(os.getenv('COURTHOUSE_PORT', '8050'))
RUN_LOCK = threading.Lock()
ALLOWED_STATIC = {'/':'index.html','/index.html':'index.html',
                  '/style.css':'style.css','/app.js':'app.js'}
CONTENT_TYPES = {'.html':'text/html; charset=utf-8', '.css':'text/css; charset=utf-8',
                 '.js':'application/javascript; charset=utf-8'}


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'Courthouse/0.7'

    def log_message(self, *args):
        if os.getenv('COURTHOUSE_HTTP_LOG', '0') == '1':
            super().log_message(*args)

    def headers_security(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy',
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'")

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.headers_security()
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == '/api/health':
            status = hosted_status()
            n = len(status.get('agents') or [])
            engine = (f'{n} server-hosted GGUF red-team AI model' + ('' if n == 1 else 's')
                      if status.get('ready') else 'server-hosted GGUF red-team AI models')
            return self.send_json(200, {'ok':True,
                'target_mode':'Upload one local target GGUF model',
                'attack_engine':engine,
                'target_inference_ready':status['inference_installed'],
                'agents_ready':status['ready'],'agents_preloaded':status['preloaded'],
                'agents':status['agents'],'agent_error':status['error'],
                'max_upload_bytes':MAX_BYTES,'strategy':'Red Team',
                'scripted_fallback':False,'red_team_uploads_required':0})
        if path not in ALLOWED_STATIC:
            return self.send_json(404, {'error':'Not found'})
        file = STATIC / ALLOWED_STATIC[path]
        body = file.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', CONTENT_TYPES.get(file.suffix, 'application/octet-stream'))
        self.send_header('Content-Length', str(len(body)))
        self.headers_security()
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == '/api/upload':
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/octet-stream':
                return self.send_json(415, {'error':'Upload a raw GGUF file.'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                info = save_upload(self.rfile, length, self.headers.get('X-Model-Filename', ''))
                return self.send_json(200, info)
            except (ValueError, FileExistsError) as exc:
                return self.send_json(400, {'error':str(exc)})
            except Exception:
                return self.send_json(500, {'error':'Could not store uploaded GGUF.'})
        if path != '/api/run':
            return self.send_json(404, {'error':'Not found'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send_json(415, {'error':'Expected JSON'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 2 <= size <= 8192:
                raise ValueError('Assessment request size invalid.')
            request = json.loads(self.rfile.read(size))
            if request.get('authorized') is not True:
                return self.send_json(403, {'error':'Confirm authorization to test the model.'})
            if request.get('strategy') != 'red_team':
                raise ValueError('Red Team is the only Courthouse strategy.')
            mode = request.get('mode', 'full')
            if mode not in ('quick', 'full'):
                raise ValueError('mode must be "quick" or "full".')
            verdict = request.get('verdict', 'rule')
            if verdict not in VERDICT_MODES:
                raise ValueError('verdict must be "rule" or "ai".')
            target_id = str((request.get('target') or {}).get('model_id', ''))
            target, agent_infos = validate_hosted_assessment(target_id, request.get('agents'))
            try:
                import llama_cpp  # noqa: F401
            except ImportError:
                raise ValueError('Install llama-cpp-python using your platform setup script.')
            if not RUN_LOCK.acquire(blocking=False):
                return self.send_json(409, {'error':'An assessment is already running.'})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self.send_json(400, {'error':str(exc)})

        labels = [info['file'] for info in agent_infos]
        label_to_id = {label: info['model_id'] for label, info in zip(labels, agent_infos)}

        def emit(event):
            line = (json.dumps(event, ensure_ascii=False) + '\n').encode('utf8')
            self.wfile.write(f'{len(line):X}\r\n'.encode() + line + b'\r\n')
            self.wfile.flush()

        # Live transcript: every exact prompt/reply between jurors and the target is streamed
        # as a 'dialogue' event before and after each inference call (same thread as emit).
        purposes = {id(ATTACK_SCHEMA): 'attack generation', id(INDIVIDUAL_SCHEMA): 'individual report',
                    id(MESSAGE_SCHEMA): 'jury message', id(SUMMARY_SCHEMA): 'joint summary',
                    id(VERDICT_SCHEMA): 'verdict'}
        seq = [0]

        def dialogue(agent, role, **fields):
            seq[0] += 1
            emit({'type': 'dialogue', 'agent': agent, 'role': role, 'seq': seq[0], 'timestamp': now(), **fields})
            return seq[0]

        def local_chat(label, messages, temperature, max_tokens, schema=None):
            # Actual inference on the corresponding server-hosted red-team GGUF weights.
            agent = labels.index(label) + 1
            ref = dialogue(agent, 'juror_prompt', model=label, purpose=purposes.get(id(schema), 'juror call'),
                           messages=messages, temperature=temperature, max_tokens=max_tokens)
            try:
                text = chat_uploaded(label_to_id[label], messages, temperature, max_tokens, schema=schema,
                                     quick=mode == 'quick')
            except Exception as exc:
                dialogue(agent, 'error', reply_to=ref, model=label, text=f'{type(exc).__name__}: {exc}')
                raise
            dialogue(agent, 'juror_reply', reply_to=ref, model=label, text=text)
            return text

        def run_target(case):
            agent = int(case.id.split('-', 1)[0])
            ref = dialogue(agent, 'target_prompt', model=target['name'], case=case.id,
                           messages=[{'role': 'system', 'content': case.system},
                                     {'role': 'user', 'content': case.attack}],
                           tools=[t['function']['name'] for t in case.tools])
            try:
                response = run_local(case, target_id)
            except Exception as exc:
                dialogue(agent, 'error', reply_to=ref, model=target['name'], text=f'{type(exc).__name__}: {exc}')
                raise
            dialogue(agent, 'target_reply', reply_to=ref, model=target['name'], case=case.id,
                     text=response.get('content', ''), tool_calls=response.get('tool_calls') or [])
            return response

        try:
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
            self.send_header('Transfer-Encoding', 'chunked')
            self.headers_security()
            self.end_headers()

            try:
                for event in assess_stream(target_id, target['name'], target['sha256'],
                         labels, local_chat, run_target, mode=mode, verdict=verdict):
                    emit(event)
            except Exception as exc:
                emit({'type':'error', 'message':f'Courthouse assessment interrupted: {type(exc).__name__}: {str(exc)[:220]}'})
            self.wfile.write(b'0\r\n\r\n')
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            RUN_LOCK.release()


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == '__main__':
    print('Scanning models/agents for server-hosted Courthouse GGUF weights...')
    state = initialize_hosted_agents()
    if state['ready']:
        print(f"{len(state['agents'])} Courthouse model(s) ready; preloaded={state['preloaded']}.")
    else:
        print('AGENTS NOT READY: '+state['error'])
        print('Place one or more distinct .gguf files in models/agents (list refreshes live).')
    print(f'Courthouse v7 | http://{HOST}:{PORT}')
    print('Upload only the TARGET GGUF from the browser. No scripted fallback.')
    print('Local private development only; do not expose publicly without authentication and sandboxing.')
    Server((HOST, PORT), Handler).serve_forever()
