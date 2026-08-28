import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from _parse import parse_serp, scrape_markdown  # noqa: E402

FC_URL = "https://api.firecrawl.dev/v1/scrape"
TIMEOUT = 45


def read_q(handler):
    parsed = urllib.parse.urlparse(handler.path)
    qs = urllib.parse.parse_qs(parsed.query)
    q = (qs.get("q") or [None])[0]
    if q:
        return q.strip()[:180]
    length = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(min(length, 1_000_000)).decode("utf-8", "replace") if length else ""
    if not raw:
        return ""
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if isinstance(body, dict):
        return str(body.get("q") or "").strip()[:180]
    return ""


def firecrawl_scrape(url, key):
    payload = json.dumps(
        {"url": url, "formats": ["markdown"], "onlyMainContent": True}
    ).encode("utf-8")
    req = urllib.request.Request(
        FC_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "User-Agent": "envi-serp-proxy/1",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def search(q):
    key = (os.environ.get("FIRECRAWL_API_KEY") or "").strip()
    if not key:
        return {"error": "missing FIRECRAWL_API_KEY"}, 500
    q = (q or "").strip()[:180]
    if not q:
        return {"error": "empty query"}, 400
    source = "https://www.amazon.com/s?k=" + urllib.parse.quote_plus(q)
    try:
        payload = firecrawl_scrape(source, key)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        return {"error": "firecrawl HTTP %s" % e.code, "detail": detail}, 502
    except Exception as e:
        return {"error": "firecrawl failed", "detail": type(e).__name__}, 502
    md = scrape_markdown(payload)
    if not md:
        return {"error": "empty markdown", "sourceUrl": source}, 502
    data = parse_serp(md, q, source)
    if not data.get("results"):
        return {"error": "no organic results", "sourceUrl": source}, 404
    return data, 200


class handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.end_headers()

    def do_GET(self):
        payload, status = search(read_q(self))
        self.send_json(payload, status)

    def do_POST(self):
        payload, status = search(read_q(self))
        self.send_json(payload, status)
