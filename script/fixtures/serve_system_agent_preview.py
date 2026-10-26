"""Serve fictional read-only UI data on loopback; no DB or provider connection."""
import argparse
import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from system_agent_preview import response, export

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=18089)
    parser.add_argument('--export',type=Path,help='Save the same fictional data as JSON inside the project')
    args=parser.parse_args()
    if args.export:
        project=Path(__file__).resolve().parents[2]
        target=args.export.resolve()
        if not target.is_relative_to(project):
            parser.error('Export target must be inside the project')
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(export(),ensure_ascii=False,indent=2),encoding='utf-8')
    class Handler(BaseHTTPRequestHandler):
        def handle_request(self):
            path=urlparse(self.path).path
            body=None
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<0 or length>131072:
                    self.send_error(413); return
                if length: body=json.loads(self.rfile.read(length))
                result=response(path,self.command,'SUPERVISOR',self.path,body)
            except (ValueError,TypeError,AttributeError):
                result=(400,{'code':400,'message':'Invalid preview request'})
            if result is None: result=(503,{'code':503,'message':'只读预览未提供此功能，不代表服务器业务状态'})
            status,payload=result
            mime='image/svg+xml' if path.startswith('/api/demo/images/') else 'text/plain; charset=utf-8' if isinstance(payload,str) else 'application/json; charset=utf-8'
            data=(payload if isinstance(payload,str) else json.dumps(payload,ensure_ascii=False)).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Preview-Data','fictional-read-only')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            if self.command!='HEAD': self.wfile.write(data)
        do_GET=do_HEAD=do_POST=do_PUT=do_DELETE=do_PATCH=do_OPTIONS=handle_request
        def log_message(self,*args): pass
    class PreviewServer(ThreadingHTTPServer):
        allow_reuse_address=False
        def server_bind(self):
            if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
                self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            super().server_bind()
    server=PreviewServer(('127.0.0.1',args.port),Handler)
    print(f'Read-only fictional preview API: http://127.0.0.1:{args.port}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=='__main__': main()
