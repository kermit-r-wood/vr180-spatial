"""Local-only VR180 framing UI. Serves web assets without exposing source photos."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import argparse
import urllib.parse
import threading

EXPORT_SLOT = threading.Lock()

ROOT=Path(__file__).resolve().parent

class Handler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/api/export-spatial':
            self.export_spatial()
            return
        if self.path != '/api/depth':
            self.send_error(404)
            return
        # The browser sends only a reduced preview to this loopback server.
        if self.headers.get('Origin') not in (None, f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
            self.send_error(403)
            return
        import json, base64
        try:
            import cv2
            import numpy as np
            from depth_preview import estimate_depth
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 8*1024*1024:
                raise ValueError('Preview request is too large')
            source = cv2.imdecode(np.frombuffer(self.rfile.read(length), np.uint8), cv2.IMREAD_COLOR)
            if source is None:
                raise ValueError('Invalid image')
            result, stats = estimate_depth(source)
            ok, png = cv2.imencode('.png', result)
            if not ok:
                raise ValueError('PNG encoding failed')
            body = json.dumps({'image':'data:image/png;base64,'+base64.b64encode(png).decode(), **stats}).encode()
            status = 200
        except (ValueError, cv2.error) as error:
            body = json.dumps({'error':str(error)}).encode()
            status = 400
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def export_spatial(self):
        import json
        import subprocess
        from web_export import export_spatial, validate_frame
        if self.headers.get('Origin') not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
            self.send_error(403)
            return
        if not EXPORT_SLOT.acquire(blocking=False):
            self.send_error(409, 'An export is already running')
            return
        try:
            frame = json.loads(self.headers.get('X-VR180-Frame', '{}'))
            validate_frame(frame)
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 100*1024*1024:
                raise ValueError('原图需小于 100 MB')
            body = export_spatial(frame, self.rfile.read(length))
            content_type, status = 'image/heic', 200
        except (ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as error:
            body = json.dumps({'error':str(error)}, ensure_ascii=False).encode('utf-8')
            content_type, status = 'application/json', 400
        finally:
            EXPORT_SLOT.release()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(ROOT/'web'),**kwargs)
    def do_GET(self):
        if urllib.parse.urlparse(self.path).path == '/api/capabilities':
            body = b'{"spatial_export":true,"depth":true}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--open-browser', action='store_true')
    args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'VR180 framing studio: http://127.0.0.1:{args.port}',flush=True)
    if args.open_browser:
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{args.port}')
    server.serve_forever()
