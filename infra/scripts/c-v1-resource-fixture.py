"""CI-only synthetic directory: not B's service or an approved resource policy."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer " + os.environ["CAMPUS_RESOURCES_SERVICE_TOKEN"]:
            self.send_error(403)
            return
        room = {"id": "1", "name": "Synthetic C reference room", "location": "CI only", "access_scope": "campus", "department_id": None, "enabled": True}
        path = urlparse(self.path).path
        if path == "/api/v1/resources/rooms/1":
            value = room
        elif path == "/api/v1/resources/rooms":
            value = {"items": [room], "total": 1, "limit": 100, "offset": 0}
        else:
            self.send_error(404)
            return
        payload = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    if os.environ.get("CI") != "true" or not os.environ.get("CAMPUS_RESOURCES_SERVICE_TOKEN"):
        raise SystemExit("Use only with explicit synthetic CI configuration")
    ThreadingHTTPServer(("127.0.0.1", 18111), Handler).serve_forever()
