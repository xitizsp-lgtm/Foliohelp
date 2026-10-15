from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from news import get_watchlist, save_watchlist, fetch_news
from quotes import get_quote

app = FastAPI()


class Company(BaseModel):
    name: str


@app.get("/api/watchlist")
def watchlist():
    return [{"name": n, "news": fetch_news(n)} for n in get_watchlist()]


@app.get("/api/quotes")
def quotes():
    return [get_quote(n) for n in get_watchlist()]


@app.post("/api/watchlist")
def add(c: Company):
    items, name = get_watchlist(), c.name.strip()
    if name and name.lower() not in [i.lower() for i in items]:
        items.append(name)
        save_watchlist(items)
    return {"ok": True}


@app.delete("/api/watchlist/{name}")
def remove(name: str):
    save_watchlist([i for i in get_watchlist() if i != name])
    return {"ok": True}


app.mount("/", StaticFiles(directory="frontend", html=True))  # keep last