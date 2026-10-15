import json, time, urllib.parse, urllib.request

_sym = {}     # company name -> ticker symbol
_quote = {}   # ticker -> (time, data)
UA = {"User-Agent": "Mozilla/5.0"}


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    return json.loads(urllib.request.urlopen(req, timeout=8).read())


def find_symbol(name):
    """Look up a ticker for a company name. Prefers NSE (.NS), then BSE (.BO)."""
    if name in _sym:
        return _sym[name]
    sym = None
    try:
        q = urllib.parse.quote(name)
        data = _get(f"https://query2.finance.yahoo.com/v1/finance/search?q={q}&quotesCount=8&newsCount=0")
        eq = [x["symbol"] for x in data.get("quotes", []) if x.get("quoteType") == "EQUITY"]
        sym = (next((s for s in eq if s.endswith(".NS")), None)
               or next((s for s in eq if s.endswith(".BO")), None)
               or (eq[0] if eq else None))
    except Exception:
        pass
    if sym:
        _sym[name] = sym      # only remember successes, so failures are retried
    return sym


def get_quote(name):
    """Return today's price change for a company, or change_pct=None if unavailable."""
    sym = find_symbol(name)
    if not sym:
        return {"name": name, "symbol": None, "change_pct": None}

    hit = _quote.get(sym)
    if hit and time.time() - hit[0] < 300:        # reuse for 5 minutes
        return hit[1]

    try:
        data = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=1d")
        m = data["chart"]["result"][0]["meta"]
        price = m["regularMarketPrice"]
        prev = m.get("previousClose") or m.get("chartPreviousClose")
        pct = round((price - prev) / prev * 100, 2)
        out = {"name": name, "symbol": sym, "price": price,
               "change_pct": pct, "currency": m.get("currency", "")}
    except Exception:
        return {"name": name, "symbol": sym, "change_pct": None}

    _quote[sym] = (time.time(), out)
    return out