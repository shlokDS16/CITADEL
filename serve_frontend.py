"""
Tiny no-cache static server for the CITADEL frontend.
Replaces `python -m http.server 8080` so the browser stops caching .jsx / .css.

Run from project root:
    python serve_frontend.py
or:
    python serve_frontend.py 8080
"""
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Force every response to be re-fetched. Critical for dev because we
        # have no bundler version-stamping the .jsx / .css URLs by default.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, fmt, *args):
        # Quieter than default — prefix with method + status only
        sys.stderr.write(f"[citadel-frontend] {fmt % args}\n")


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    handler = partial(NoCacheHandler, directory=str(ROOT))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"CITADEL frontend (no-cache) -> http://127.0.0.1:{port}/CITADEL.html")
    print(f"Live mode                    -> http://127.0.0.1:{port}/CITADEL.html?live=1")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
