"""Crawler: official mall pages (+ optional Google-grounded search) -> own extractor (+ Gemini as
last resort) -> web/offers.json. See heuristics.py for the own-made extraction engine; ai.py is now
only consulted when that engine finds nothing on a page/image that looked like it had an offer."""
import os, re, json, time, hashlib, pathlib, datetime as dt
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import ai
import heuristics
import ocr

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (compatible; QatarOffersBot/1.0)"}
KEEP_DAYS = 10        # an offer disappears if no source has shown it for this many days
MAX_NEW_IMAGES = 25   # per run; the rest are read on the next run
SLEEP = float(os.environ.get("AI_SLEEP", "4"))   # stay inside free rate limits
CATS = {"fashion", "food", "electronics", "beauty", "home", "grocery", "other"}

def jload(p, d):
    try:
        return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d

def jsave(p, o):
    p = pathlib.Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")

def fetch(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return r

def text_of(soup):
    for t in soup(["script", "style", "nav", "footer", "noscript", "svg"]):
        t.decompose()
    return re.sub(r"\n{2,}", "\n", soup.get_text("\n", strip=True))

def find_images(soup, base, spec):
    out, seen = [], set()
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if spec.get("image_contains", "/uploads/") not in src:
            continue
        url = urljoin(base, src)
        if url in seen:
            continue
        box = img.find_parent(["li", "article", "div"])
        ctx = box.get_text(" ", strip=True)[:250] if box else ""
        if spec.get("context_must") and spec["context_must"] not in ctx:
            continue
        seen.add(url); out.append((url, ctx))
    return out

def sitemap_urls(spec):
    """Best effort: newest pages of a sitemap whose address contains spec['contains']."""
    try:
        xml = fetch(spec["url"]).text
        for child in [u for u in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml) if u.endswith(".xml")][:5]:
            xml += fetch(child).text
        items = re.findall(r"<loc>\s*([^<]+?)\s*</loc>(?:\s*<lastmod>\s*([^<]+?)\s*</lastmod>)?", xml)
        items = [(u, m or "") for u, m in items if spec.get("contains", "") in u and not u.endswith(".xml")]
        return [u for u, _ in sorted(items, key=lambda x: x[1], reverse=True)[:8]]
    except Exception as e:
        print("sitemap skipped:", e)
        return []

def clean_date(v):
    try:
        return dt.date.fromisoformat(v).isoformat() if isinstance(v, str) else None
    except ValueError:
        return None

def s300(v):
    return v.strip()[:300] if isinstance(v, str) and v.strip() else None

def normalize(o, today):
    if not isinstance(o, dict):
        return None
    store, title = s300(o.get("store_name")), s300(o.get("title"))
    if not store or not title:
        return None
    end, start = clean_date(o.get("end_date")), clean_date(o.get("start_date"))
    if end and end < today:
        return None
    if start and end and start > end:
        start = None
    url = o.get("source_url")
    return {"store_name": store, "title": title, "title_ar": s300(o.get("title_ar")),
            "description": s300(o.get("description")), "discount_text": s300(o.get("discount_text")),
            "category": o.get("category") if o.get("category") in CATS else "other",
            "start_date": start, "end_date": end, "language": s300(o.get("language")),
            "source_url": url if isinstance(url, str) and re.match(r"https?://", url) else None}

def add_offers(st, mall, offers, source_url, branch, today, origin="heuristic"):
    ids = []
    for raw in offers:
        o = normalize(raw, today)
        if not o:
            continue
        if branch:
            o["description"] = ((o["description"] or "") + f" Branch: {branch}.").strip()
        key = f"{mall['id']}|{o['store_name'].lower()}|{o['title'].lower()}|{o['end_date']}|{branch}"
        i = hashlib.sha1(key.encode()).hexdigest()[:16]
        old = st["offers"].get(i)
        st["offers"][i] = {**o, "id": i, "mall_id": mall["id"], "mall_name": mall["name"],
                           "source_url": o["source_url"] or source_url, "origin": origin,
                           "first_seen": old["first_seen"] if old else today, "last_seen": today}
        ids.append(i)
    return ids

def touch(st, ids, today):
    for i in ids:
        if i in st["offers"]:
            st["offers"][i]["last_seen"] = today

def main(root=ROOT):
    root = pathlib.Path(root)
    T = dt.date.today().isoformat()
    cfg = jload(root / "sources.json", {"malls": []})
    st = jload(root / "data/state.json", {})
    for k in ("pages", "images", "searched", "offers"):
        st.setdefault(k, {})
    status, new_images = [], 0
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    for mall in cfg["malls"]:
        pages = list(mall.get("pages", []))
        if mall.get("sitemap"):
            known = {p["url"] for p in pages}
            found = sitemap_urls(mall["sitemap"])
            pages += [{"url": u, "type": "text"} for u in found if u not in known]
        srcs, notes = [], []
        for pg in pages:
            url = pg["url"]
            try:
                html = fetch(url).text
            except Exception as e:
                notes.append(f"could not open {url.split('//')[-1][:60]}: {str(e)[:80]}")
                print("skip page", url, e); continue
            srcs.append({"title": url.split("//")[-1][:60], "url": url})
            soup = BeautifulSoup(html, "html.parser")
            if pg.get("type") == "images":
                imgs = find_images(soup, url, pg)
                if not imgs:
                    notes.append(f"no promo images matched on {url.split('//')[-1][:60]}"
                                 f" (looking for '{pg.get('image_contains', '/uploads/')}'"
                                 + (f" near '{pg['context_must']}'" if pg.get('context_must') else "") + ")")
                found_here = 0
                for img_url, ctx in imgs:
                    rec = st["images"].get(img_url)
                    if rec:                                  # already read before: no re-read
                        touch(st, rec["offer_ids"], T); found_here += len(rec["offer_ids"]); continue
                    if new_images >= MAX_NEW_IMAGES:
                        continue
                    try:
                        r = fetch(img_url)
                    except Exception as e:
                        print("skip image", img_url, e); continue
                    if len(r.content) > 6_000_000:
                        continue
                    mime = (r.headers.get("content-type") or "image/jpeg").split(";")[0]
                    text = ocr.ocr_text(r.content)
                    offers = heuristics.extract_offers_from_image_text(text, ctx, mall["name"], pg.get("branch"), T)
                    origin = "ocr"
                    if not offers:
                        ai_offers = ai.image_offers(r.content, mime, ctx, mall["name"], pg.get("branch"), T)
                        if ai_offers is not None:
                            offers, origin = ai_offers, "ai_image"
                    ids = add_offers(st, mall, offers, url, pg.get("branch"), T, origin)
                    st["images"][img_url] = {"offer_ids": ids}
                    found_here += len(ids)
                    new_images += 1
                    time.sleep(0.1 if origin != "ai_image" else SLEEP)
                if imgs and not found_here:
                    notes.append(f"{len(imgs)} promo image(s) found on {url.split('//')[-1][:60]} but no offer could be read from them")
            else:
                text = text_of(soup)
                h = hashlib.sha1(text.encode()).hexdigest()
                rec = st["pages"].get(url)
                if rec and rec["hash"] == h:                  # page unchanged: nothing new to do
                    touch(st, rec["offer_ids"], T)
                    continue
                offers = heuristics.extract_offers_from_text(text, mall["name"], url, T)
                origin = "heuristic"
                if not offers and len(text) >= 60:
                    ai_offers = ai.text_offers(text, mall["name"], url, T)
                    if ai_offers is not None:
                        offers, origin = ai_offers, "ai_text"
                    time.sleep(SLEEP)
                if not offers:
                    short = url.split('//')[-1][:60]
                    if len(text) < 60:
                        notes.append(f"{short} returned almost no readable text "
                                     "(page may need JavaScript to show its content)")
                    else:
                        notes.append(f"no offer-shaped text found on {short}")
                st["pages"][url] = {"hash": h, "offer_ids": add_offers(st, mall, offers, url, None, T, origin)}
        if mall.get("search") and st["searched"].get(mall["id"]) != T:   # at most once a day per mall
            res = ai.search_offers(mall["name"], mall.get("area"), T)
            if res is not None:
                add_offers(st, mall, res[0], None, None, T, "ai_search")
                srcs += res[1]
                st["searched"][mall["id"]] = T
            elif not ai.search_allowed():
                notes.append("web search disabled (GEMINI_MODE=off)")
        status.append({"id": mall["id"], "checked_at": now, "sources": srcs[:10], "notes": notes[:6]})

    today = dt.date.fromisoformat(T)
    for i, o in list(st["offers"].items()):
        ended = o.get("end_date") and o["end_date"] < T
        stale = (today - dt.date.fromisoformat(o["last_seen"])).days > KEEP_DAYS
        if ended or stale:
            del st["offers"][i]
    pub = ["id", "store_name", "mall_name", "title", "title_ar", "description", "discount_text",
           "category", "start_date", "end_date", "source_url", "language", "origin"]
    live = sorted(st["offers"].values(), key=lambda o: (o.get("end_date") or "9999", o["store_name"]))
    jsave(root / "web/offers.json", {"updated": now, "status": status, "offers": [{k: o.get(k) for k in pub} for o in live]})
    jsave(root / "web/malls.json", [{k: m.get(k) for k in ("id", "name", "name_ar", "area")} for m in cfg["malls"]])
    jsave(root / "data/state.json", st)
    print(f"done: {len(live)} live offers, {new_images} new images read, "
          f"{ai._calls['n']} Gemini extraction call(s) used (mode={ai._mode()})")

if __name__ == "__main__":
    main()
