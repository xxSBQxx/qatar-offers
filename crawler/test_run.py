"""Offline test: fake mall pages + fake AI. Run: python crawler/test_run.py"""
import os, sys, json, pathlib, tempfile, datetime as dt
os.environ["AI_SLEEP"] = "0"
os.environ["GEMINI_API_KEY"] = "test"
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import run, ai

today = dt.date.today()
fut = (today + dt.timedelta(days=20)).isoformat()
past = (today - dt.timedelta(days=5)).isoformat()

EZDAN = """<ul>
<li><img src="/uploads/images/a.jpg">Promotion 19 Jul 2026- 18 Oct 2026 <h4>Special Offer</h4></li>
<li><img src="/uploads/images/b.jpg">Promotion 01 Sep 2026- 31 Dec 2026 <h4>Buy 1 get 1 Free</h4></li>
<li><img src="/uploads/images/a.jpg">Promotion duplicate</li>
<li><img src="/web_assets/images/logo.png">logo</li>
<li><img src="/uploads/images/c.jpg">News item without the keyword</li></ul>"""
MOQ = "<html><body><nav>menu</nav><h1>Mega Sale</h1><p>Nike up to 50% off</p></body></html>"

class R:
    def __init__(s, text="", content=b"img"): s.text, s.content, s.headers = text, content, {"content-type": "image/jpeg"}

PAGES = {"https://e.test/promotions": EZDAN, "https://m.test/sale": MOQ}
def fake_fetch(url):
    if url in PAGES: return R(PAGES[url])
    if "/uploads/" in url: return R(content=b"jpgbytes")
    raise RuntimeError("404 " + url)

calls = {"img": 0, "txt": 0, "search": 0}
def img(data, mime, ctx, mall, branch, t):
    calls["img"] += 1
    return [{"store_name": "Zara" if "Special" in ctx else "Next", "title": "Sale", "category": "fashion",
             "start_date": "2026-01-01", "end_date": fut}, {"store_name": "Old", "title": "Gone", "end_date": past}]
def txt(text, mall, url, t):
    calls["txt"] += 1
    return [{"store_name": "Nike", "title": "Up to 50% off", "discount_text": "50%", "category": "weird"}]
def search(mall, area, t):
    calls["search"] += 1
    return [{"store_name": "Bad", "title": "x", "source_url": "javascript:1"}, "junk"], [{"title": "g", "url": "https://g.test"}]
run.fetch, ai.image_offers, ai.text_offers, ai.search_offers = fake_fetch, img, txt, search

root = pathlib.Path(tempfile.mkdtemp())
(root / "sources.json").write_text(json.dumps({"malls": [
  {"id": "ezdan", "name": "Ezdan Mall", "pages": [{"url": "https://e.test/promotions", "type": "images", "branch": "Al Wakra", "context_must": "Promotion"}]},
  {"id": "moq", "name": "Mall of Qatar", "pages": [{"url": "https://m.test/sale", "type": "text"}], "search": True}]}))

run.main(root)
out = json.loads((root / "web/offers.json").read_text())
names = sorted(o["store_name"] for o in out["offers"])
assert names == ["Bad", "Next", "Nike", "Zara"], names           # expired 'Old' dropped, junk ignored
assert calls == {"img": 2, "txt": 1, "search": 1}, calls          # duplicate/logo/keyword-less images skipped
assert all(o["category"] in run.CATS for o in out["offers"])
assert [o for o in out["offers"] if o["store_name"] == "Bad"][0]["source_url"] is None   # unsafe url removed
assert "Branch: Al Wakra" in [o for o in out["offers"] if o["store_name"] == "Zara"][0]["description"]
assert len(out["status"]) == 2 and out["status"][1]["sources"][-1]["url"] == "https://g.test"

run.main(root)                                                      # second run, nothing changed
assert calls == {"img": 2, "txt": 1, "search": 1}, calls          # NO new AI calls (cached)

# an offer nobody has shown for 11 days disappears
st = json.loads((root / "data/state.json").read_text())
k = next(i for i, o in st["offers"].items() if o["store_name"] == "Nike")
st["offers"][k]["last_seen"] = (today - dt.timedelta(days=11)).isoformat()
st["pages"] = {}                                                    # and its page no longer touches it
PAGES["https://m.test/sale"] = ""; ai.text_offers = lambda *a: []
(root / "data/state.json").write_text(json.dumps(st))
run.main(root)
out = json.loads((root / "web/offers.json").read_text())
assert "Nike" not in [o["store_name"] for o in out["offers"]]
print("all crawler tests passed")
