import json, time, urllib.parse, urllib.request
from datetime import datetime, timezone
 
_sym = {}     # company name -> ticker symbol
_quote = {}   # ticker -> (time, data)
_hist = {}    # (ticker, date) -> closing price (past prices never change)
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
    """Return the current price and today's % change, or change_pct=None if unavailable."""
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
 
 
def price_on(sym, date_str):
    """Closing price on the first trading day on or after date_str (YYYY-MM-DD)."""
    key = (sym, date_str)
    if key in _hist:
        return _hist[key]
    price = None
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        p1 = int(d.timestamp())
        p2 = p1 + 10 * 86400                      # look up to 10 days ahead (weekends, holidays)
        data = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
                    f"?period1={p1}&period2={p2}&interval=1d")
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        price = next((c for c in closes if c), None)
    except Exception:
        pass
    if price:
        _hist[key] = price
    return price
 