import feedparser, json, re, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from googlenewsdecoder import gnewsdecoder   # optional, used for article thumbnails
except ImportError:
    gnewsdecoder = None

WATCH = Path("watchlist.json")   # saved in the folder you run the server from
_cache = {}                      # company -> (time, headlines)
_img = {}                        # article link -> thumbnail url

def get_watchlist():
    if WATCH.exists():
        return json.loads(WATCH.read_text(encoding="utf-8"))
    return []

def save_watchlist(items):
    WATCH.write_text(json.dumps(items), encoding="utf-8")

def thumbnail(link):
    if link in _img:
        return _img[link]
    img = ""
    if gnewsdecoder:
        try:
            real = gnewsdecoder(link).get("decoded_url")
            req = urllib.request.Request(real, headers={"User-Agent": "Mozilla/5.0"})
            html = urllib.request.urlopen(req, timeout=5).read(200000).decode("utf-8", "ignore")
            m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html)
            img = m.group(1) if m else ""
        except Exception:
            pass
    _img[link] = img
    return img

def fetch_news(company, limit=5):
    hit = _cache.get(company)
    if hit and time.time() - hit[0] < 900:       # reuse results for 15 minutes
        return hit[1]

    q = urllib.parse.quote(f"{company} when:7d")  # news from the last 7 days
    url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
    feed = feedparser.parse(url)

    items = []
    for e in feed.entries[:limit]:
        src = e.get("source", {})
        domain = urllib.parse.urlparse(src.get("href", "")).netloc
        items.append({
            "title": e.title,
            "link": e.link,
            "source": src.get("title", ""),
            "published": e.get("published", ""),
            "logo": f"https://www.google.com/s2/favicons?domain={domain}&sz=64" if domain else "",
        })

    if gnewsdecoder and items:
        with ThreadPoolExecutor(5) as ex:
            for item, img in zip(items, ex.map(lambda i: thumbnail(i["link"]), items)):
                item["image"] = img

    _cache[company] = (time.time(), items)
    return items