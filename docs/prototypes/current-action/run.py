"""Throwaway UI review server. Never part of the application runtime."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class PrototypeHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _serve_config(self, include_body):
        if self.path.split("?", 1)[0] != "/prototype-config.js":
            return False
        content = b"window.SMALLNEXT_PROTOTYPE = true;\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/javascript; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        if include_body:
            self.wfile.write(content)
        return True

    def do_GET(self):
        if not self._serve_config(include_body=True):
            super().do_GET()

    def do_HEAD(self):
        if not self._serve_config(include_body=False):
            super().do_HEAD()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8767), PrototypeHandler)
    print("시제품: http://127.0.0.1:8767/?variant=A", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
