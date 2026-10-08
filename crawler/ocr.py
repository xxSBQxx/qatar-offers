"""Reads text out of promo banner images ourselves (Tesseract OCR), so we don't
have to send every banner image to Gemini. If Tesseract isn't installed on the
machine running this, ocr_text() just returns None and the caller falls back
to whatever caption text the web page already had (see heuristics.py), and
only as a last resort to Gemini vision."""
import io

_warned = False


def ocr_text(image_bytes):
    global _warned
    try:
        import pytesseract
        from PIL import Image
    except Exception as e:
        if not _warned:
            print("OCR unavailable (pytesseract/Pillow not installed):", e)
            _warned = True
        return None
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode not in ("L", "RGB"):
            img = img.convert("RGB")
        txt = pytesseract.image_to_string(img)
        return txt.strip() or None
    except Exception as e:
        print("OCR failed on image:", str(e)[:150])
        return None
