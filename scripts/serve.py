# python3 serve.py
# then open http://127.0.0.1:8765
import json
import os
import re
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote_plus, urlparse

ROOT = Path(__file__).resolve().parent.parent
HOST = "127.0.0.1"
PORT = 8765
TIMEOUT = 90
CLI = ["npx", "-y", "firecrawl-cli@latest"]
SECRET_RE = re.compile(
    r"(?i)(fc-[a-z0-9_-]{8,}|sk-[a-z0-9_-]{8,}|api[_-]?key[\"'\s:=]+[^\s\"']+)"
)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")
CARD_RE = re.compile(
    r"\[!\[([^\]]*)\]\((https://m\.media-amazon\.com/images/I/[^)]+)\)\]"
    r"\(https://www\.amazon\.com/([^/\s)\"']+)/dp/([A-Z0-9]{10})/ref=(sr_1_\d+)[^)]*\)"
)
COUNT_RE = re.compile(r"(\d+-\d+ of (?:over )?[\d,]+ results)", re.I)


def redact(text):
    if not text:
        return ""
    text = ANSI_RE.sub("", str(text))
    return SECRET_RE.sub("<redacted>", text)


def parse_money(raw):
    if raw is None:
        return None
    try:
        return float(str(raw).replace(",", "").replace("$", ""))
    except ValueError:
        return None


def extract_json_blob(text):
    text = redact(text).strip()
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    blob = text[start : end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def scrape_markdown(payload):
    if payload is None:
        return ""
    if isinstance(payload, str):
        data = extract_json_blob(payload)
        if data is None:
            return payload
        payload = data
    if not isinstance(payload, dict):
        return ""
    for key in ("markdown", "content"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("markdown", "content"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            for key in ("markdown", "content"):
                val = first.get(key)
                if isinstance(val, str) and val.strip():
                    return val
    return ""



def card_window(md, start):
    nxt = CARD_RE.search(md, start + 1)
    end = nxt.start() if nxt else min(len(md), start + 1800)
    return md[start:end]


ESRB_MAP = {
    "Everyone": "Todos",
    "Everyone 10+": "Todos +10",
    "Teen": "Adolescentes",
    "Mature": "Maduro",
}


def extra_line(chunk):
    m = re.search(r"ESRB Rating:\s*([^\n]+)", chunk)
    if not m:
        return None
    raw = m.group(1).replace("\\", "").split("|")[0].strip()
    mapped = ESRB_MAP.get(raw, raw)
    return f"Calificación de la ESRB: {mapped}"


def brand_line(chunk, asin, title):
    links = re.findall(
        rf"\[([^\]]{{2,48}})\]\(https://www\.amazon\.com/[^)]+/dp/{asin}",
        chunk,
    )
    title_l = (title or "").lower()
    for label in links:
        label = label.replace("**", "").strip()
        if not label or label.lower() in title_l:
            continue
        if re.search(r"\$\d|click to see|out of 5|^\(?[\d,]+\)?$", label, re.I):
            continue
        if len(label) <= 40:
            return label
    return None


def parse_card(md, match, position, sponsored=False):
    alt, image, slug, asin, sr = match.groups()
    chunk = card_window(md, match.start())
    title = alt.strip()
    bold = re.search(
        rf"\[\*\*([^\]]+)\*\*\]\(https://www\.amazon\.com/[^)]+/dp/{asin}",
        chunk,
    )
    if bold:
        title = bold.group(1).strip()
    rating = None
    rm = re.search(r"(\d(?:\.\d)?)_?\d(?:\.\d)? out of 5 stars", chunk)
    if rm:
        rating = float(rm.group(1))
    reviews = None
    rc = re.search(r"\[\(?([\d,]+)\)?\]\([^)]+#customerReviews\)", chunk)
    if rc:
        try:
            reviews = int(rc.group(1).replace(",", ""))
        except ValueError:
            reviews = None
    map_hidden = bool(re.search(r"Click to see price|See price in cart", chunk, re.I))
    price = None
    price_label = None
    if map_hidden:
        price_label = "Ver precio"
    else:
        pm = re.search(r"\$(\d[\d,]*\.\d{2})", chunk)
        if pm:
            price = parse_money(pm.group(1))
            price_label = f"${pm.group(1)}"
    bought = None
    bm = re.search(r"([\d]+K?\+)\s+bought in past month", chunk, re.I)
    if bm:
        bought = bm.group(1)
    prime = bool(re.search(r"Join Prime|Prime delivery|\bPrime\b", chunk))
    delivery = None
    dm = re.search(
        r"((?:FREE delivery|Get it)\s+[A-Za-z]+(?:,\s+[A-Za-z]+\s+\d{1,2})?(?:\s+\d{1,2})?(?:\s*-\s*\d{1,2})?)",
        chunk,
    )
    if dm:
        delivery = dm.group(1).strip()
    stock = None
    sm = re.search(r"(Only \d+ left in stock[^\n.]*)", chunk)
    if sm:
        stock = sm.group(1).strip().rstrip(".")
    ahead = (md or "")[max(0, match.start() - 500) : match.start()] + chunk
    badge = None
    if re.search(r"Overall Pick", ahead):
        badge = "Selección general"
    elif re.search(r"Amazon'?s Choice", ahead):
        badge = "Amazon's Choice"
    url = f"https://www.amazon.com/{slug}/dp/{asin}/ref={sr}"
    extra = extra_line(chunk)
    brand = brand_line(chunk, asin, title)
    return {
        "position": position,
        "asin": asin,
        "title": title,
        "url": url,
        "image": image,
        "rating": rating,
        "reviewCount": reviews,
        "price": price,
        "priceLabel": price_label,
        "mapHidden": map_hidden,
        "boughtPastMonth": bought,
        "prime": prime,
        "delivery": delivery,
        "stock": stock,
        "sponsored": sponsored,
        "badge": badge,
        "extra": extra,
        "brand": brand,
    }


SPON_RE = re.compile(
    r"\[!\[([^\]]*)\]\((https://m\.media-amazon\.com/images/I/[^)]+)\)\]"
    r"\((https://(?:aax-[^)\s]+|www\.amazon\.com/[^)\s]+/dp/[A-Z0-9]{10})[^)]*)\)"
)


def parse_sponsored(md, seen):
    out = []
    for match in SPON_RE.finditer(md or ""):
        alt, image, url = match.groups()
        window = (md or "")[match.end() : match.end() + 2500]
        if "aax-" not in url:
            continue
        asin_m = re.search(r"/dp/([A-Z0-9]{10})", url)
        asin = asin_m.group(1) if asin_m else None
        if not asin or asin in seen:
            continue
        bold = re.search(r"Sponsored\[\*\*([^\]]+)\*\*\]", window)
        title = bold.group(1).replace("\\", "").strip() if bold else alt.strip()
        rating = None
        rm = re.search(r"(\d(?:\.\d)?)_?\d(?:\.\d)? out of 5 stars", window)
        if rm:
            rating = float(rm.group(1))
        reviews = None
        rc = re.search(r"\[\(?([\d,]+)\)?\]\([^)]+#customerReviews\)", window)
        if rc:
            try:
                reviews = int(rc.group(1).replace(",", ""))
            except ValueError:
                reviews = None
        price = None
        price_label = None
        pm = re.search(r"\$(\d[\d,]*\.\d{2})", window)
        if pm:
            price = parse_money(pm.group(1))
            price_label = f"${pm.group(1)}"
        bought = None
        bm = re.search(r"([\d]+K?\+)\s+bought in past month", window, re.I)
        if bm:
            bought = bm.group(1)
        extra = extra_line(window)
        seen.add(asin)
        out.append(
            {
                "position": 0,
                "asin": asin,
                "title": title,
                "url": "https://www.amazon.com/dp/" + asin,
                "image": image,
                "rating": rating,
                "reviewCount": reviews,
                "price": price,
                "priceLabel": price_label,
                "mapHidden": False,
                "boughtPastMonth": bought,
                "prime": True,
                "delivery": None,
                "stock": None,
                "sponsored": True,
                "badge": None,
                "extra": extra,
                "brand": None,
            }
        )
        if len(out) >= 1:
            break
    return out


def parse_serp(md, query, source_url):
    md = md or ""
    count_m = COUNT_RE.search(md.replace('"', "").replace("\\#", ""))
    label = count_m.group(1) if count_m else None
    seen = set()
    results = []
    for match in CARD_RE.finditer(md):
        asin = match.group(4)
        if asin in seen:
            continue
        if "aax-us-" in match.group(0):
            continue
        seen.add(asin)
        results.append(parse_card(md, match, len(results) + 1))
    for i, spon in enumerate(parse_sponsored(md, seen)):
        insert_at = 1 if results else 0
        results.insert(insert_at + i, spon)
    for i, item in enumerate(results, 1):
        item["position"] = i
    extracted = []
    if results:
        extracted.extend(["title", "asin", "image"])
    if any(r.get("rating") is not None for r in results):
        extracted.append("rating")
    if any(r.get("reviewCount") for r in results):
        extracted.append("reviewCount")
    if any(r.get("price") is not None or r.get("mapHidden") for r in results):
        extracted.append("price or MAP hint")
    if any(r.get("boughtPastMonth") for r in results):
        extracted.append("boughtPastMonth")
    if any(r.get("delivery") for r in results):
        extracted.append("delivery")
    if any(r.get("extra") for r in results):
        extracted.append("ESRB/extra")
    if any(r.get("sponsored") for r in results):
        extracted.append("sponsored")
    lost = [
        "buy-box exact price on Overall Pick",
        "filters/sidebar",
        "full sponsored creative",
        "variants",
    ]
    if not label:
        label = f"{len(results)} results"
    return {
        "query": query or "",
        "sourceUrl": source_url,
        "resultCountLabel": label,
        "shipTo": "ONBM · Miami 33166",
        "results": results,
        "coverage": {
            "extracted": extracted,
            "lost": lost,
            "organicCards": sum(1 for r in results if not r.get("sponsored")),
            "markdownBytes": len(md.encode("utf-8")),
        },
    }


def run_cli(args, timeout=TIMEOUT):
    env = os.environ.copy()
    env.pop("FIRECRAWL_API_KEY", None)
    try:
        proc = subprocess.run(
            CLI + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "npx missing"
    out = redact(proc.stdout)
    err = redact(proc.stderr)
    return proc.returncode, out, err


def search_url(q):
    return "https://www.amazon.com/s?k=" + quote_plus(q)


def live_search(q):
    q = (q or "").strip()[:180]
    if not q:
        return {"error": "empty query"}, 400
    url = search_url(q)
    code, out, err = run_cli([url, "--only-main-content"])
    if code != 0:
        return {"error": "scrape failed", "detail": (err or out)[:400]}, 502
    md = scrape_markdown(out) or out
    data = parse_serp(md, q, url)
    if not data["results"]:
        return {"error": "no organic results", "sourceUrl": url}, 404
    return data, 200


class LocalHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        msg = redact(fmt % args)
        sys.stderr.write("%s - %s\n" % (self.address_string(), msg))

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
        path = urlparse(self.path).path
        if path in ("/api/results", "/api/results.json"):
            target = ROOT / "results.json"
            if not target.exists():
                self.send_json({"error": "missing results.json"}, 404)
                return
            data = json.loads(target.read_text(encoding="utf-8"))
            self.send_json(data)
            return
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/search":
            self.send_json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(length, 1_000_000)).decode("utf-8", "replace")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self.send_json({"error": "invalid JSON"}, 400)
            return
        q = body.get("q") if isinstance(body, dict) else None
        payload, status = live_search(q)
        self.send_json(payload, status)


def main():
    os.chdir(ROOT)
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer((HOST, PORT), LocalHandler)
    print(f"http://{HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
