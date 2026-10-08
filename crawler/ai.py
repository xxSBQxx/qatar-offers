"""All Gemini calls live here. Functions return None on failure (retry next run), [] when nothing was found.

Gemini is now a LAST RESORT, not the main engine (see crawler/heuristics.py, which runs first and
needs no API key). Two env vars control how much this file is used:
  GEMINI_MODE     "fallback" (default) = only called when the own-made extractor found nothing on a
                  page/image that looked like it had an offer. "off" = never call Gemini at all.
  GEMINI_CALL_CAP max text/image extraction calls per run (default 5). Grounded web search
                  (search_offers) is separate: already capped to once/day/mall, still skipped entirely
                  when GEMINI_MODE is "off".
"""
import os, re, json, time
from google import genai
from google.genai import types

_client = None
_picked = {}
_calls = {"n": 0}

def _mode():
    return os.environ.get("GEMINI_MODE", "fallback").strip().lower()

def _cap():
    try:
        return int(os.environ.get("GEMINI_CALL_CAP", "5"))
    except ValueError:
        return 5

def enabled():
    """Is Gemini usable at all this run (API key present and not turned off)?"""
    return _mode() != "off" and bool(os.environ.get("GEMINI_API_KEY"))

def budget_ok():
    """Allowed to make one more text/image extraction call right now?
    Callers should try crawler/heuristics.py FIRST and only ask this for the
    handful of pages where it came up empty."""
    return enabled() and _calls["n"] < _cap()

def search_allowed():
    """Grounded web search has its own once-a-day-per-mall cap in run.py; this just
    respects the global off switch."""
    return enabled()

def client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client

def _ver(n):
    m = re.search(r"gemini-(\d+)(?:\.(\d+))?", n)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)

def pick_model(kind):
    """Newest stable Flash model ('lite' = cheapest). Survives Google retiring old model names."""
    if kind in _picked:
        return _picked[kind]
    names = []
    for m in client().models.list():
        n = m.name.replace("models/", "")
        acts = getattr(m, "supported_actions", None) or []
        if ("generateContent" in acts and n.startswith("gemini-") and "flash" in n
                and not re.search(r"image|tts|live|audio|preview|exp|thinking|robotics|computer|native|embed", n)):
            names.append(n)
    pool = [n for n in names if ("lite" in n) == (kind == "lite")] or names
    if not pool:
        raise RuntimeError("no Gemini model available")
    _picked[kind] = max(pool, key=_ver)
    print("using model:", _picked[kind])
    return _picked[kind]

def _gen(kind, contents, config=None):
    model = os.environ.get("EXTRACT_MODEL" if kind == "lite" else "SEARCH_MODEL") or pick_model(kind)
    for attempt in range(4):
        try:
            return client().models.generate_content(model=model, contents=contents, config=config)
        except Exception as e:
            s = str(e)
            if "NOT_FOUND" in s or "404" in s:
                _picked.pop(kind, None)
                os.environ.pop("EXTRACT_MODEL" if kind == "lite" else "SEARCH_MODEL", None)
                model = pick_model(kind)
                continue
            print("  retry after:", s[:150])
            time.sleep(15 * (attempt + 1))
    return None

RULES = ("Rules: list only real offers that the source shows. Never guess dates, prices or percentages (use null). "
         "Skip offers that ended before {today}. Copy store names exactly as written. "
         'Output ONLY a JSON array. Each item: {"store_name","title","title_ar" (Arabic translation of the title),'
         '"description","discount_text","category" (fashion|food|electronics|beauty|home|grocery|other),'
         '"start_date" (YYYY-MM-DD or null),"end_date" (YYYY-MM-DD or null),"language"}. If there are none, output [].')

def _text(r):
    try:
        return r.text or ""
    except Exception:
        return ""

def parse_array(text):
    clean = (text or "").replace("```json", "").replace("```", "")
    s, e = clean.find("["), clean.rfind("]")
    if s < 0 or e < s:
        return None
    try:
        v = json.loads(clean[s:e + 1])
        return v if isinstance(v, list) else None
    except Exception:
        return None

def text_offers(text, mall, url, today):
    if not budget_ok():
        return None
    _calls["n"] += 1
    p = (f"Today is {today}. Source: official web page of {mall} ({url}).\n"
         + RULES.replace("{today}", today) + "\n\nPAGE TEXT:\n" + text[:30000])
    r = _gen("lite", [p], types.GenerateContentConfig(response_mime_type="application/json"))
    return parse_array(_text(r)) if r else None

def image_offers(data, mime, ctx, mall, branch, today):
    if not budget_ok():
        return None
    _calls["n"] += 1
    p = (f"Today is {today}. This image is a promotion banner from {mall}" + (f" ({branch} branch)" if branch else "") + ". "
         f'Text shown next to it on the web page: "{ctx}". Use those dates as start and end dates unless the image shows different ones. '
         "Read the store or brand name and the offer from the image. " + RULES.replace("{today}", today))
    r = _gen("lite", [types.Part.from_bytes(data=data, mime_type=mime), p],
             types.GenerateContentConfig(response_mime_type="application/json"))
    return parse_array(_text(r)) if r else None

def search_offers(mall, area, today):
    if not search_allowed():
        return None
    p = (f"Today is {today}. Use Google Search to find CURRENT offers, sales and discounts at stores inside {mall}"
         + (f" ({area})" if area else "") + ", Qatar. Only include offers you found evidence for. "
         "Add to each item a source_url (the page where you saw it, or null). " + RULES.replace("{today}", today))
    cfg = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])
    r = _gen("flash", [p], cfg)
    arr = parse_array(_text(r)) if r else None
    if arr is None:
        return None
    try:
        ch = r.candidates[0].grounding_metadata.grounding_chunks or []
        src = [{"title": c.web.title or c.web.uri, "url": c.web.uri} for c in ch if c.web and c.web.uri][:6]
    except Exception:
        src = []
    return arr, src
