"""CLI and trusted-operator demo web server (Python 3.12 standard library)."""
import gzip
import argparse
import json
import os
import socket
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from app.config import ROOT, load_env, sample_mode, setting
from app.engines.world_model.registry import Registry, Conflict
from app.pipeline import Pipeline
from app.geo.hazards import map_data
from app.geo.depth import depth_data


def reachability(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        with socket.create_connection((parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)), timeout=1):
            return 'reachable (TCP only; credentials not checked)'
    except (OSError, ValueError):
        return 'unreachable'


def create_server(host='0.0.0.0', port=8080, sample=None, registry_path=None, pipeline=None):
    offline = sample_mode() if sample is None else sample
    registry = pipeline.registry if pipeline else Registry(registry_path or ROOT/'runtime/events.jsonl')
    pipeline = pipeline or Pipeline(registry, sample=offline)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Raw paths and requests can contain identifiers.

        def send_json(self, code, data, compress=False):
            body = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode()
            if compress:
                body = gzip.compress(body, mtime=0)
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            if compress:
                self.send_header('Content-Encoding', 'gzip')
            self.send_header('Vary', 'Accept-Encoding')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urllib.parse.urlsplit(self.path).path
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query, keep_blank_values=True)
            try:
                from app.web import routes_v2
            except ImportError:
                pass
            else:
                if routes_v2.handle_get(self, path, query):
                    return
            if path == '/':
                body = (ROOT/'app/web/index.html').read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(body)
            elif path == '/api/health':
                self.send_json(200, {'SAMPLE_MODE': offline, 'mode': 'sample_offline' if offline else 'live',
                    'Nightshift': 'unavailable (offline)' if offline else reachability(setting('NIGHTSHIFT_BASE_URL', 'http://127.0.0.1:8088/v1')),
                    'Zetaris': 'unavailable (offline)' if offline else reachability(setting('ZETARIS_REST_URL', 'http://localhost:8888/api/v1.0'))})
            elif path == '/api/depth':
                try:
                    query=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query,keep_blank_values=True)
                    if len(query.get('date',[]))!=1 or len(query.get('bbox',[]))!=1:
                        raise ValueError('Provide exactly one date and bbox')
                    self.send_json(200,depth_data(query['date'][0],query['bbox'][0]))
                except ValueError as exc:
                    self.send_json(400,{'error':str(exc)})
            elif path == '/api/map':
                try:
                    dates = query.get('date', [])
                    if len(dates) != 1:
                        raise ValueError('Provide exactly one date=YYYY-MM-DD')
                    payload = map_data(dates[0], registry.read())
                    encodings = {}
                    for item in self.headers.get('Accept-Encoding', '').lower().split(','):
                        parts = item.strip().split(';')
                        try:
                            encodings[parts[0]] = float(next((p.strip()[2:] for p in parts[1:] if p.strip().startswith('q=')), '1'))
                        except ValueError:
                            encodings[parts[0]] = 0
                    self.send_json(200, payload, compress=encodings.get('gzip', encodings.get('*', 0)) > 0)
                except ValueError as exc:
                    self.send_json(400, {'error': str(exc)})
            elif path == '/api/cases':
                self.send_json(200, {'cases': registry.read()})
            elif path.startswith('/api/cases/') and path.endswith('/card'):
                from app.dispatch_card import build_card
                case = registry.read(path.split('/')[3])
                self.send_json(200 if case else 404, build_card(case) if case else {'error':'Caso n?o encontrado.'})
            elif path.startswith('/api/cases/'):
                case = registry.read(path.rsplit('/', 1)[1])
                self.send_json(200 if case else 404, case or {'error': 'Caso não encontrado.'})
            else:
                self.send_json(404, {'error': 'Rota não encontrada.'})

        def do_POST(self):
            try:
                # Same-origin browser controls protect human commands against cross-site requests.
                origin = self.headers.get('Origin')
                if origin and urllib.parse.urlsplit(origin).netloc != self.headers.get('Host'):
                    self.send_json(403, {'error': 'Origem não permitida.'})
                    return
                if not self.headers.get('Content-Type', '').startswith('application/json'):
                    self.send_json(415, {'error': 'Use application/json.'})
                    return
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 256000:
                    raise ValueError('JSON ausente ou maior que 256 KB.')
                self.connection.settimeout(10)
                request = json.loads(self.rfile.read(length).decode('utf-8'))
                path = urllib.parse.urlsplit(self.path).path
                if path == '/run':
                    self.send_json(200, pipeline.run(request))
                elif path.startswith('/api/cases/') and path.endswith('/reply'):
                    self.send_json(200, pipeline.reply(path.split('/')[3], request))
                elif path.startswith('/api/cases/') and path.endswith('/actions'):
                    if not isinstance(request, dict):
                        raise ValueError('Envie um objeto JSON.')
                    cid = path.split('/')[3]
                    case = registry.action(cid, request.get('action'), request.get('expected_version'), request.get('actor'), human=True,
                                           asset=request.get('asset'), caution_acknowledged=request.get('caution_acknowledged',False))
                    self.send_json(200, case)
                else:
                    self.send_json(404, {'error': 'Rota não encontrada.'})
            except Conflict as exc:
                self.send_json(409, {'error': str(exc)})
            except (ValueError, TypeError, UnicodeError) as exc:
                # Avoid echoing malformed JSON, which can contain personal data.
                self.send_json(400, {'error': str(exc) if type(exc) is ValueError else 'JSON ou parâmetros inválidos.'})
            except KeyError:
                self.send_json(404, {'error': 'Caso não encontrado.'})
            except Exception:
                self.send_json(500, {'error': 'Falha interna; confira a configuração local.'})
    return ThreadingHTTPServer((host, port), Handler)


def main():
    # Windows redirected consoles can default to cp1252; WhatsApp-style text may
    # contain emoji. Keep CLI JSON and traces valid UTF-8 even when redirected.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', choices=['serve'])
    parser.add_argument('--sample', action='store_true')
    parser.add_argument('--input', type=Path)
    args = parser.parse_args()
    offline = args.sample or sample_mode()
    if args.command == 'serve':
        server = create_server(port=int(setting('PORT', '8080')), sample=offline)
        print(f'Mesa de triagem: http://localhost:{server.server_port}; SAMPLE_MODE={offline}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    if not args.input:
        parser.error('Use --input examples/input_01.json ou serve')
    try:
        request = json.loads(args.input.read_text(encoding='utf-8-sig'))
        result = Pipeline(Registry(ROOT/'runtime/events.jsonl'), sample=offline).run(request)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 2 if result['partial'] else 0
    except Exception as exc:
        print('Falha: '+type(exc).__name__+'; confira entrada e configuração.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
