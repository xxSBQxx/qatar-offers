"""
Own-made offer extractor. No AI calls, no API key needed.

This is the PRIMARY way offers are found. It reads the same flattened page text
the AI path used to get (one visible text node per line, produced by run.text_of)
and looks for lines that smell like a real offer: a percentage, "buy 1 get 1",
"free", "sale", "discount", etc. Store names are picked up either from a pattern
inside the offer line itself ("Nike: up to 50% off", "50% off at Zara") or from
the nearest short, non-sentence "heading-like" line above it (works well for
mall listing pages, which are almost always "Store name" then "offer text").

Gemini (crawler/ai.py) is only asked for help when this finds nothing at all on
a page that otherwise looks like it should have something -- see run.py.
"""
import re
import datetime as dt

try:
    from dateutil import parser as dateparser
except Exception:  # pragma: no cover - dateutil ships in requirements.txt
    dateparser = None

NOISE_WORDS = ("cookie", "privacy", "subscribe", "newsletter", "javascript",
               "sign in", "log in", "terms of", "all rights reserved", "©")
# Lines that use offer-ish words but are describing the mall in general, not an actual live deal.
NEGATION_RE = re.compile(
    r"\bno\s+(?:offer|discount|sale)s?\b|\bwithout\s+(?:offer|discount)|"
    r"\b(?:we|mall|store|shop)\w*\s+offers?\s+(?:a|an|the|wide|variety|range|selection)\b", re.I)

PCT_RE = re.compile(r"\b\d{1,3}\s?%")
# Gate: a line only counts as an offer if it has a number+% or one of these specific, hard-to-fake
# deal phrases. Bare words like "sale"/"discount"/"offer" are deliberately NOT enough on their own --
# they show up constantly in ordinary marketing copy ("Mall of Qatar offers a wide variety...").
STRONG_RE = re.compile(
    r"(\d{1,3}\s?%|buy\s*1\s*get\s*1|buy\s+one\s+get\s+one|\bbogo\b|flat\s+\d{1,3}\b|"
    r"free\s+(?:gift|delivery)\b|clearance\s+sale|mega\s+sale|sale\s+now\s+on|up\s+to\s+\d)", re.I)
NOISE_RE = re.compile("|".join(re.escape(w) for w in NOISE_WORDS), re.I)

DISCOUNT_RE = re.compile(
    r"(up to \d{1,3}\s?%(?:\s?off)?|flat \d{1,3}\s?%(?:\s?off)?|\d{1,3}\s?%\s?off|"
    r"buy\s*1\s*get\s*1(?:\s*free)?|buy\s+one\s+get\s+one(?:\s*free)?|bogo|"
    r"free\s+(?:gift|delivery)|\d{1,3}\s?%)", re.I)

_NAME = r"[A-Z][\w&'.]*(?:\s+(?:&|[A-Z][\w&'.]*)){0,3}"  # a short run of Capitalized Words (a brand name)
STORE_PATTERNS = [
    re.compile(r"^(" + _NAME + r")\s*[:\-–]\s+\S"),          # "Zara: 50% off"
    re.compile(r"\bat\s+(" + _NAME + r")\b"),                 # "50% off at Zara"
    re.compile(r"^(" + _NAME + r")\s+(?:offers?|presents?|is offering)\b"),  # "Zara offers 50%"
    re.compile(r"^([A-Z][\w&'.]*(?:\s+(?:&|[A-Z][\w&'.]*)){0,2})\b"),  # last resort: leading capitalized words ("Nike up to 50% off")
]
# Words that can start a sentence capitalized but are never themselves a store name --
# without this the last-resort pattern above would mis-tag lines like "Flat 20% off..." or
# "Mega Sale this weekend" as a store called "Flat" or "Mega".
_NOT_A_STORE = {"flat", "up", "buy", "sale", "offer", "offers", "discount", "discounts", "mega",
                "clearance", "free", "today", "now", "exclusive", "limited", "special", "promo",
                "promotion", "promotions", "valid", "new", "get", "save", "enjoy", "shop", "shopping",
                "welcome", "ends", "starts", "starting", "from", "until", "all", "every", "this"}

CATS_KW = {
    "fashion": ("fashion", "cloth", "apparel", "wear", "shoe", "bag", "accessor", "jewel", "watch"),
    "food": ("restaurant", "food", "cafe", "café", "dining", "coffee", "dessert", "menu", "bakery", "kitchen"),
    "electronics": ("electronic", "mobile", "phone", "laptop", "gadget", "appliance", "tv", "tech"),
    "beauty": ("beauty", "cosmetic", "perfume", "salon", "spa", "skincare", "makeup"),
    "home": ("home", "furnitur", "decor", "kitchenware", "homeware"),
    "grocery": ("grocery", "supermarket", "hypermarket", "mart"),
}


def guess_category(text):
    low = text.lower()
    for cat, kws in CATS_KW.items():
        if any(k in low for k in kws):
            return cat
    return "other"


def _is_heading_like(line):
    words = line.split()
    if not (1 <= len(words) <= 5):
        return False
    if any(ch.isdigit() for ch in line):
        return False
    if STRONG_RE.search(line):
        return False
    return bool(re.match(r"^[A-Z][A-Za-z&'.\- ]+$", line))


def _guess_store(line, fallback):
    for pat in STORE_PATTERNS:
        m = pat.search(line)
        if not m:
            continue
        name = m.group(1).strip(" :-–")
        words = name.split()
        if 1 <= len(words) <= 5 and words[0].lower() not in _NOT_A_STORE:
            return name
    return fallback


def _discount_text(line):
    m = DISCOUNT_RE.search(line)
    return m.group(0).strip() if m else None


_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_DATEY_RE = re.compile(
    r"\b(\d{1,2}\s*(?:st|nd|rd|th)?\s*[A-Za-z]{3,9}\s*\d{2,4}|"
    r"[A-Za-z]{3,9}\s+\d{1,2}(?:,)?\s*\d{2,4}|"
    r"\d{4}-\d{2}-\d{2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4})\b", re.I)


def _parse_one_date(s, today_year):
    if not dateparser:
        return None
    try:
        d = dateparser.parse(s, fuzzy=True, default=dt.datetime(today_year, 1, 1))
        return d.date().isoformat()
    except Exception:
        return None


def _extract_dates(context, today):
    """Looks for 'start - end' style date ranges, or a single end date, inside a chunk of text."""
    today_year = dt.date.fromisoformat(today).year
    found = _DATEY_RE.findall(context)
    if not found:
        return None, None
    if len(found) == 1:
        return None, _parse_one_date(found[0], today_year)
    s, e = _parse_one_date(found[0], today_year), _parse_one_date(found[1], today_year)
    if s and e and s > e:
        s, e = e, s
    return s, e


def extract_offers_from_text(text, mall, url, today, max_items=40):
    """Rule-based pass over flattened page text. Returns a list of offer dicts
    (same loose shape run.normalize() expects), or [] if nothing looked like a
    real offer. Never raises; never calls the network."""
    lines = [l.strip() for l in (text or "").split("\n") if l.strip()]
    offers, headings = [], []
    for idx, line in enumerate(lines):
        if NOISE_RE.search(line):
            continue
        if _is_heading_like(line):
            headings.append(line)
            headings = headings[-3:]
            continue
        if not STRONG_RE.search(line):
            continue
        if NEGATION_RE.search(line):
            continue
        if len(line) > 320:
            continue
        store = _guess_store(line, headings[-1] if headings else None)
        if not store:
            continue
        start, end = _extract_dates(line, today)
        if start is None and end is None and len(lines) <= 4:
            # Only widen the search to neighboring lines when the whole snippet is tiny (e.g. OCR
            # text + the page's own caption for a single banner image -- see extract_offers_from_image_text).
            # On a long page we deliberately do NOT do this: picking up a neighboring, unrelated
            # offer's date is worse than leaving the date blank.
            window = " ".join(lines[max(0, idx - 1):idx + 2])
            start, end = _extract_dates(window, today)
        offers.append({
            "store_name": store,
            "title": line[:120],
            "description": line[:300],
            "discount_text": _discount_text(line),
            "category": guess_category(line + " " + store),
            "start_date": start,
            "end_date": end,
            "language": "ar" if re.search(r"[\u0600-\u06FF]", line) else "en",
            "source_url": url,
        })
        if len(offers) >= max_items:
            break
    return offers


def extract_offers_from_image_text(ocr_text, ctx, mall, branch, today):
    """Same engine, used on OCR'd banner text plus whatever caption/context text
    the web page already showed next to the image (dates are often only in ctx)."""
    combined = "\n".join(t for t in (ocr_text, ctx) if t)
    return extract_offers_from_text(combined, mall, None, today)
