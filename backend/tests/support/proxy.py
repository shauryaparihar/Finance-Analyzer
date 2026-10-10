"""
A tiny reverse proxy used to imitate what a hosting rewrite does in front of the API: it forwards requests to the
backend and returns the response. With strip_set_cookie=True it behaves like a broken proxy that drops cookies.
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

DROPPED = {"transfer-encoding", "connection", "content-length", "content-encoding"}


def start_proxy(port: int, upstream: str, strip_set_cookie: bool = False) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _forward(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            headers = {k: v for k, v in self.headers.items() if k.lower() not in {"host", "content-length", "connection"}}
            reply = httpx.request(self.command, f"{upstream}{self.path}", headers=headers, content=body, timeout=15)
            self.send_response(reply.status_code)
            for key, value in reply.headers.multi_items():
                if key.lower() in DROPPED or (strip_set_cookie and key.lower() == "set-cookie"):
                    continue
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(reply.content)))
            self.end_headers()
            self.wfile.write(reply.content)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _forward

        def log_message(self, *args):  # keep test output quiet
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
