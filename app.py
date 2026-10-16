import hashlib, hmac, os, re, sqlite3
from datetime import datetime, date
 
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
 
from news import fetch_news
from quotes import get_quote, price_on
 
DB_PATH = os.environ.get("DB_PATH", "foliohelp.db")
SECRET = os.environ.get("SECRET_KEY", "dev-only-change-me")   # set a long random SECRET_KEY when hosting
 
app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET,
    max_age=60 * 60 * 24 * 30,                 # stay logged in for 30 days
    same_site="lax",
    https_only=bool(os.environ.get("RENDER")),  # secure cookies when hosted on Render
)
 
 
# ---------- database ----------
def run(sql, args=(), fetch=False):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(sql, args)
        rows = cur.fetchall() if fetch else cur.lastrowid
        con.commit()
        return rows
    finally:
        con.close()
 
 
_con = sqlite3.connect(DB_PATH)
_con.executescript("""
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS watch(user_id INTEGER NOT NULL, name TEXT NOT NULL, UNIQUE(user_id, name));
CREATE TABLE IF NOT EXISTS invest(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, company TEXT NOT NULL,
                                  amount REAL NOT NULL, invested_on TEXT NOT NULL, buy_price REAL);
""")
_con.close()
 
 
# ---------- passwords ----------
def hash_pw(pw, salt=None):
    salt = salt or os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)
    return salt.hex() + ":" + h.hex()
 
 
def check_pw(pw, stored):
    salt_hex, h_hex = stored.split(":")
    h = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    return hmac.compare_digest(h.hex(), h_hex)
 
 
# ---------- login ----------
def current_user(request: Request):
    uid = request.session.get("uid")
    if uid and run("SELECT 1 FROM users WHERE id=?", (uid,), True):
        return uid
    request.session.clear()
    raise HTTPException(401, "Not logged in")
 
 
class Auth(BaseModel):
    username: str
    password: str
 
 
class Company(BaseModel):
    name: str
 
 
class Invest(BaseModel):
    company: str
    amount: float
    date: str
    buy_price: float | None = None
 
 
@app.post("/api/register")
def register(a: Auth, request: Request):
    name = a.username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{3,30}", name):
        raise HTTPException(400, "Username: 3-30 letters, numbers or underscores")
    if len(a.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    try:
        uid = run("INSERT INTO users(username, pw) VALUES(?, ?)", (name, hash_pw(a.password)))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "That username is taken")
    request.session["uid"] = uid
    return {"ok": True}
 
 
@app.post("/api/login")
def login(a: Auth, request: Request):
    rows = run("SELECT id, pw FROM users WHERE username=?", (a.username.strip().lower(),), True)
    if not rows or not check_pw(a.password, rows[0]["pw"]):
        raise HTTPException(400, "Wrong username or password")
    request.session["uid"] = rows[0]["id"]
    return {"ok": True}
 
 
@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}
 
 
@app.get("/api/me")
def me(uid: int = Depends(current_user)):
    return {"username": run("SELECT username FROM users WHERE id=?", (uid,), True)[0]["username"]}
 
 
# ---------- watchlist (private to each user) ----------
def names(uid):
    return [r["name"] for r in run("SELECT name FROM watch WHERE user_id=? ORDER BY rowid", (uid,), True)]
 
 
@app.get("/api/watchlist")
def watchlist(uid: int = Depends(current_user)):
    return [{"name": n, "news": fetch_news(n)} for n in names(uid)]
 
 
@app.get("/api/quotes")
def quotes(uid: int = Depends(current_user)):
    return [get_quote(n) for n in names(uid)]
 
 
@app.post("/api/watchlist")
def add_company(c: Company, uid: int = Depends(current_user)):
    name = c.name.strip()[:80]
    if name:
        run("INSERT OR IGNORE INTO watch(user_id, name) VALUES(?, ?)", (uid, name))
    return {"ok": True}
 
 
@app.delete("/api/watchlist/{name}")
def remove_company(name: str, uid: int = Depends(current_user)):
    run("DELETE FROM watch WHERE user_id=? AND name=?", (uid, name))
    return {"ok": True}
 
 
# ---------- investments (private to each user) ----------
@app.post("/api/investments")
def add_investment(i: Invest, uid: int = Depends(current_user)):
    company = i.company.strip()[:80]
    if not company or i.amount <= 0 or (i.buy_price is not None and i.buy_price <= 0):
        raise HTTPException(400, "Enter a company, a positive amount and (optionally) a positive buy price")
    try:
        d = datetime.strptime(i.date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "Enter a valid date")
    if d > date.today():
        raise HTTPException(400, "The investment date can't be in the future")
    run("INSERT INTO invest(user_id, company, amount, invested_on, buy_price) VALUES(?,?,?,?,?)",
        (uid, company, i.amount, i.date, i.buy_price))
    return {"ok": True}
 
 
@app.delete("/api/investments/{iid}")
def remove_investment(iid: int, uid: int = Depends(current_user)):
    run("DELETE FROM invest WHERE id=? AND user_id=?", (iid, uid))
    return {"ok": True}
 
 
@app.get("/api/investments")
def investments(uid: int = Depends(current_user)):
    rows = run("SELECT * FROM invest WHERE user_id=? ORDER BY invested_on DESC, id DESC", (uid,), True)
    items, tot_in, tot_val, currencies = [], 0.0, 0.0, set()
    for r in rows:
        q = get_quote(r["company"])
        sym, price = q.get("symbol"), q.get("price")
        buy = r["buy_price"] or (price_on(sym, r["invested_on"]) if sym else None)
        item = {"id": r["id"], "company": r["company"], "amount": r["amount"], "date": r["invested_on"],
                "symbol": sym, "currency": q.get("currency", ""), "buy_price": buy, "price": price,
                "value": None, "profit": None, "profit_pct": None}
        if buy and price:
            value = r["amount"] / buy * price
            item.update(value=round(value, 2), profit=round(value - r["amount"], 2),
                        profit_pct=round((value / r["amount"] - 1) * 100, 2))
            tot_in += r["amount"]
            tot_val += value
            currencies.add(item["currency"])
        items.append(item)
    summary = None
    if len(currencies) == 1:
        summary = {"invested": round(tot_in, 2), "value": round(tot_val, 2), "profit": round(tot_val - tot_in, 2)}
    return {"items": items, "summary": summary}
 
 
app.mount("/", StaticFiles(directory="frontend", html=True))  # keep las