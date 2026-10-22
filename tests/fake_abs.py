"""A tiny fake Audiobookshelf used by the integration tests.

It implements just enough of the API for a full OPDS request: login, libraries,
items, authors, series, collections, item details and the current-user probe.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ITEMS = {
    "results": [
        {
            "id": "book-1",
            "addedAt": 1700000000000,
            "media": {
                "ebookFormat": "epub",
                "metadata": {
                    "title": "Book One",
                    "authorName": "Ann & Bob",
                    "authors": [
                        {"id": "author-ann", "name": "Ann"},
                        {"id": "author-bob", "name": "Bob"},
                    ],
                    "series": {"name": "Saga", "sequence": None},
                    "genres": [],
                },
            },
        },
        {
            "id": "book-2",
            "addedAt": 1700000001000,
            "media": {
                "ebookFormat": "epub",
                "metadata": {
                    "title": "Book Two",
                    "authorName": "Ann",
                    "authors": [{"id": "author-ann", "name": "Ann"}],
                    "series": {"name": "Saga", "sequence": "1-2"},
                    "genres": [],
                },
            },
        },
    ]
}

AUTHORS = {
    "authors": [
        {"id": "author-ann", "name": "Ann"},
        {"id": "author-bob", "name": "Bob"},
    ]
}

SERIES = {"results": [{"id": "series-1", "name": "Saga", "books": ["book-1", "book-2"]}]}


class Handler(BaseHTTPRequestHandler):
    """Request handler implementing the fake API."""

    def log_message(self, *args):
        """Silence request logging."""

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        """Handle /login."""
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")

        if self.path != "/login":
            self._json({"error": "not found"}, 404)
            return

        password = payload.get("password")
        if password == "secret":
            self._json({"user": {"token": "user-token", "username": "reader", "type": "user"}})
        elif password == "admin":
            self._json({"user": {"token": "admin-token", "username": "reader", "type": "admin"}})
        else:
            self._json({"error": "invalid credentials"}, 401)

    def do_GET(self):
        """Handle the read-only API."""
        path = urlparse(self.path).path
        bearer = self.headers.get("Authorization", "")

        if path == "/api/me":
            user_type = "admin" if bearer == "Bearer admin-token" else "user"
            self._json({"id": "u1", "username": "reader", "type": user_type})
        elif path == "/api/libraries":
            self._json({"libraries": [{"id": "lib1", "name": "Library"}]})
        elif path == "/api/libraries/lib1/items":
            self._json(ITEMS)
        elif path == "/api/libraries/lib1/authors":
            self._json(AUTHORS)
        elif path == "/api/libraries/lib1/series":
            self._json(SERIES)
        elif path == "/api/libraries/lib1/collections":
            self._json({"results": []})
        elif path.startswith("/api/items/"):
            item_id = path.split("/")[3]
            self._json({
                "id": item_id,
                "libraryFiles": [
                    {"ino": "77", "fileType": "ebook", "metadata": {"filename": "book.epub"}}
                ],
            })
        else:
            self._json({"error": "not found", "path": path}, 404)


def start_server():
    """Start the fake server on a free port.

    Returns:
        tuple: (ThreadingHTTPServer, base_url)
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}"
