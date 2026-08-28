# python3 serve.py
# then open http://127.0.0.1:8765
import json
import os
import re
import subprocess
import sys
from collections import Counter
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8765
TIMEOUT = 90
CLI = ["npx", "-y", "firecrawl-cli@latest"]
SECRET_RE = re.compile(
    r"(?i)(fc-[a-z0-9_-]{8,}|sk-[a-z0-9_-]{8,}|api[_-]?key[\"'\s:=]+[^\s\"']+)"
)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")
ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")
LP_ASIN_RE = re.compile(r"lp_asin=([A-Z0-9]{10})")
IMG_RE = re.compile(r"!\[([^\]]*)\]\((https://[^)\s]+)\)")
AMZ_DP_RE = re.compile(
    r"https://www\.amazon\.com/([^/\s)\"']+)/dp/([A-Z0-9]{10})"
)
SKIP_H1 = {
    "about this item",
    "why don't we show the price?",
    "product information",
    "product details",
    "from the manufacturer",
    "customers who viewed this item also viewed",
    "frequently bought together",
    "example domain",
}
LOST_CANON = [
    "buy-box exact price (MAP)",
    "weight/dims reliable",
    "Q&A",
    "full review bodies",
    "add-to-cart without Amazon login",
    "variants",
]


def redact(text):
    if not text:
        return ""
    text = ANSI_RE.sub("", str(text))
    return SECRET_RE.sub("<redacted>", text)


def clean_url(url):
    if not url:
        return url
    return url.split("?")[0].split("#")[0]


def dedupe_title(text):
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    n = len(text)
    for i in range(n // 2, 12, -1):
        if text[:i] == text[i : 2 * i]:
            return text[:i].strip()
    prefix = text[: min(40, n)]
    if len(prefix) >= 16:
        idx = text.find(prefix, 18)
        if idx > 18:
            return text[:idx].strip()
    return text


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


def search_web(search):
    if not search:
        return []
    if isinstance(search, list):
        return search
    data = search.get("data") if isinstance(search, dict) else None
    if isinstance(data, dict) and isinstance(data.get("web"), list):
        return data["web"]
    if isinstance(search, dict) and isinstance(search.get("web"), list):
        return search["web"]
    return []


def search_hits(search):
    hits = []
    seen = set()
    for item in search_web(search):
        if not isinstance(item, dict):
            continue
        url = clean_url(item.get("url") or "")
        title = (item.get("title") or "").split(" : ")[0].strip()
        m = ASIN_RE.search(url or "")
        asin = m.group(1) if m else None
        key = asin or url
        if not key or key in seen:
            continue
        seen.add(key)
        hits.append({"title": title, "url": url, "asin": asin})
    return hits


def most_common_asin(md):
    lp = LP_ASIN_RE.search(md or "")
    if lp:
        return lp.group(1)
    counts = Counter(ASIN_RE.findall(md or ""))
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def source_from_md(md, asin):
    if asin:
        tagged = re.search(
            rf"https://www\.amazon\.com/[^/\s)\"']+/dp/{asin}", md or ""
        )
        if tagged:
            return clean_url(tagged.group(0))
    found = AMZ_DP_RE.search(md or "")
    if found:
        return clean_url(found.group(0))
    return None


def product_title(md):
    for m in re.finditer(r"^#\s+(.+)$", md or "", re.M):
        title = dedupe_title(m.group(1))
        if title.lower() in SKIP_H1:
            continue
        if len(title) < 4:
            continue
        return title, m.start()
    alt = re.search(
        r"!\[([^\]\n]{8,120})\]\(https://m\.media-amazon\.com/images/I/[^)]+_SX\d+_",
        md or "",
    )
    if alt:
        return dedupe_title(alt.group(1)), alt.start()
    return None, 0


def parse_also_viewed(md, main_asin):
    m = re.search(
        r"Customers who viewed this item also viewed\s*(.*?)(?=\n##\s|\n#####\s|\n-\s+\[Video Games\]|\nPlatform\s*:)",
        md or "",
        re.S | re.I,
    )
    if not m:
        return []
    section = m.group(1)
    items = []
    seen = set()
    chunks = re.split(r"(?:^|\n)\d+\.\s+", section.strip())
    for chunk in chunks[1:]:
        img_m = IMG_RE.search(chunk)
        image = img_m.group(2) if img_m else None
        alt = img_m.group(1) if img_m else ""
        asin = None
        url = None
        title = None
        for sm, sa in AMZ_DP_RE.findall(chunk):
            if sa == main_asin:
                continue
            asin = sa
            url = f"https://www.amazon.com/{sm}/dp/{sa}"
            break
        if not asin:
            continue
        link_titles = re.findall(
            rf"\[([^\]]+)\]\(https://www\.amazon\.com/[^)]+/dp/{asin}[^)]*\)",
            chunk,
        )
        if link_titles:
            title = dedupe_title(link_titles[0])
        elif alt:
            title = dedupe_title(alt)
        prices = [parse_money(p) for p in re.findall(r"\$(\d[\d,]*\.\d{2})", chunk)]
        price = next((p for p in prices if p is not None), None)
        if asin in seen:
            continue
        seen.add(asin)
        items.append(
            {
                "title": title or asin,
                "asin": asin,
                "url": url,
                "image": image,
                "price": price,
            }
        )
        if len(items) >= 8:
            break
    return items


def parse_images(md, title):
    images = []
    seen = set()
    hero = None
    thumbs = []
    for alt, url in IMG_RE.findall(md or ""):
        if "m.media-amazon.com/images/I/" not in url:
            continue
        if any(bad in url for bad in ("sash//", "sprites", "/G/01/")):
            continue
        iid = re.search(r"/images/I/([^._]+)", url)
        key = iid.group(1) if iid else url
        if "_SX38" in url or "_SY50_CR" in url:
            if key in seen:
                continue
            seen.add(key)
            thumbs.append({"url": url, "role": "thumb"})
            continue
        if "_SX342_" in url or "_SX425_" in url or "_SX522_" in url:
            if hero is None:
                hero = {"url": url, "role": "hero"}
                seen.add(key)
            continue
    if hero is None:
        for alt, url in IMG_RE.findall(md or ""):
            if "m.media-amazon.com/images/I/" not in url:
                continue
            if title and alt and title.split("–")[0].strip()[:12].lower() in alt.lower():
                hero = {"url": url, "role": "hero"}
                break
    if hero:
        images.append(hero)
    images.extend(thumbs[:12])
    return images


def bullets_from(md):
    m = re.search(
        r"^#\s+About this item\s*\n+(.*?)(?=\n#+\s|\n›\s|\n##\s)",
        md or "",
        re.S | re.M,
    )
    if not m:
        return []
    block = m.group(1)
    out = []
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("- "):
            item = line[2:].strip()
            if item and item not in out:
                out.append(item)
    return out[:12]


def window_text(md, pos, span=2800):
    return (md or "")[pos : pos + span]


def parse_amazon_md(md, search=None, query=None):
    md = md or ""
    hits = search_hits(search)
    title, tpos = product_title(md)
    asin = None
    source_url = None
    if hits:
        source_url = hits[0].get("url")
        asin = hits[0].get("asin")
        if not title:
            title = hits[0].get("title")
    if not asin:
        asin = most_common_asin(md)
    if not source_url:
        source_url = source_from_md(md, asin)
    nearby = window_text(md, tpos)
    rating = None
    reviews = None
    rm = re.search(
        r"(\d(?:\.\d)?)\s+_?\d(?:\.\d)? out of 5 stars_?\s*\[\(?([\d,]+)\)?\]",
        nearby,
    )
    if rm:
        rating = float(rm.group(1))
        reviews = int(rm.group(2).replace(",", ""))
    else:
        rm = re.search(r"_(\d(?:\.\d)?) out of 5 stars_", nearby)
        rc = re.search(r"\[\(?([\d,]+)\)?\]", nearby)
        if rm:
            rating = float(rm.group(1))
        if rc:
            try:
                reviews = int(rc.group(1).replace(",", ""))
            except ValueError:
                reviews = None
    pm = re.search(r"Platform\s*:\s*([^\n\|]+)", md, re.I)
    platform = pm.group(1).strip().strip("\\| ") if pm else None
    brand = None
    bm = re.search(r"Visit the\s+(.+?)\s+Store", md)
    if bm:
        brand = bm.group(1).strip()
    if not brand:
        lg = re.search(r"!\[PlayStation\]", md)
        if lg:
            brand = "PlayStation"
    if not brand and title and re.search(r"PlayStation|Sony", title, re.I):
        brand = "PlayStation"
    bought = None
    bmm = re.search(r"([\d]+K?\+)\s+bought in past month", nearby, re.I)
    if bmm:
        bought = bmm.group(1)
    choice = bool(re.search(r"Amazon'?s Choice", nearby))
    avail = None
    am = re.search(
        r"^\s*(In Stock|Currently unavailable|Only \d+ left in stock[^\n]*)\s*$",
        md,
        re.M,
    )
    if am:
        avail = am.group(1).strip()
        if avail.lower().startswith("only"):
            avail = "In Stock"
    ships = None
    sm = re.search(r"Ships from:\s*([A-Za-z0-9.]+)", md, re.I)
    if sm:
        ships = sm.group(1).strip()
    elif re.search(r"Shipper / Seller\s+Amazon\.com", md):
        ships = "Amazon.com"
    eta = None
    em = re.search(r"(FREE delivery [A-Za-z]+,\s+[A-Za-z]+\s+\d{1,2})", md)
    if em:
        eta = em.group(1).strip()
    map_hidden = bool(
        re.search(r"See price in cart", md, re.I)
        or re.search(r"Why don't we show the price", md, re.I)
    )
    cart_hint = "See price in cart" if re.search(r"See price in cart", md, re.I) else None
    visible = None
    if not map_hidden:
        vm = re.search(r"\|\s*Price:\s*\|\s*\[?\$(\d[\d,]*\.\d{2})", md)
        if vm:
            visible = parse_money(vm.group(1))
    new_cond = None
    nm = re.search(r"New Condition Price:\s*\$(\d[\d,]*\.\d{2})", md)
    if nm:
        new_cond = parse_money(nm.group(1))
    images = parse_images(md, title)
    bullets = bullets_from(md)
    also = parse_also_viewed(md, asin)
    extracted = []
    if title:
        extracted.append("title")
    if asin:
        extracted.append("asin")
    if rating is not None:
        extracted.append("rating")
    if bullets:
        extracted.append("bullets")
    if images:
        extracted.append("images")
    if also:
        extracted.append("alsoViewed")
    if map_hidden:
        extracted.append("mapHidden")
    if new_cond is not None:
        extracted.append("newConditionPrice")
    if avail:
        extracted.append("availability")
    lost = []
    if map_hidden or visible is None:
        lost.append("buy-box exact price (MAP)")
    lost.append("weight/dims reliable")
    lost.append("Q&A")
    lost.append("full review bodies")
    lost.append("add-to-cart without Amazon login")
    lost.append("variants")
    ordered_lost = [x for x in LOST_CANON if x in lost]
    return {
        "query": query or "",
        "sourceUrl": source_url,
        "asin": asin,
        "title": title,
        "brand": brand,
        "platform": platform,
        "rating": rating,
        "reviewCount": reviews,
        "amazonsChoice": choice,
        "boughtPastMonth": bought,
        "availability": avail,
        "shipsFrom": ships,
        "eta": eta,
        "price": {
            "mapHidden": map_hidden,
            "visible": visible,
            "cartHint": cart_hint,
            "newCondition": new_cond,
            "currency": "USD",
        },
        "images": images,
        "bullets": bullets,
        "alsoViewed": also,
        "searchHits": hits,
        "coverage": {"extracted": extracted, "lost": ordered_lost},
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


def live_search(q):
    q = (q or "").strip()[:180]
    if not q:
        return {"error": "q vacío"}, 400
    code, out, err = run_cli(
        ["search", f"{q} site:amazon.com", "--limit", "1", "--json"]
    )
    if code != 0:
        return {"error": "búsqueda falló", "detail": (err or out)[:400]}, 502
    payload = extract_json_blob(out)
    if not payload:
        return {"error": "búsqueda sin JSON", "detail": out[:240]}, 502
    hits = search_hits(payload)
    if not hits or not hits[0].get("url"):
        return {"error": "sin resultados", "searchHits": hits}, 404
    url = hits[0]["url"]
    code, out, err = run_cli([url, "--only-main-content"])
    if code != 0:
        return {
            "error": "scrape falló",
            "detail": (err or out)[:400],
            "searchHits": hits,
        }, 502
    md = scrape_markdown(out) or out
    product = parse_amazon_md(md, search=payload, query=q)
    return product, 200


class Handler(SimpleHTTPRequestHandler):
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
        if path in ("/api/product", "/api/product.json"):
            target = ROOT / "product.json"
            if not target.exists():
                self.send_json({"error": "sin product.json"}, 404)
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
            self.send_json({"error": "JSON inválido"}, 400)
            return
        q = body.get("q") if isinstance(body, dict) else None
        product, status = live_search(q)
        self.send_json(product, status)


def main():
    os.chdir(ROOT)
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"http://{HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
