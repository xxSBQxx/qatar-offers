# Qatar Offers: fully automatic version

Every 6 hours a free robot (GitHub Actions) reads the malls' official pages, turns the text and promo
images into offers **itself** (own rule-based reading + OCR, no API calls), saves them, and republishes
the website. Gemini is only asked for help on the rare page or image the own-made reader can't make
sense of, and for an optional daily web search per mall. You do nothing after setup. The website also
installs on phones.

Covers 3 test malls: Mall of Qatar, City Center Doha, Ezdan Mall (Gharaffa, Wakra, Wukair). Edit `sources.json` to add more.

## Setup (about 15 minutes, once)
1. Create a free account at github.com. Create a **new public repository** (for example `qatar-offers`).
   (Public is required for free GitHub Pages hosting. Your Gemini key stays secret.)
2. Upload this folder's contents to the repository.
   - Easy way: on the repo page click "uploading an existing file" and drag in everything (include the `.github` folder).
     On a Mac press Cmd+Shift+. in Finder to show it. Check the repo afterwards shows `.github/workflows/refresh.yml`.
   - Or with git: `git init`, `git add .`, `git commit -m start`, `git branch -M main`, `git remote add origin <repo-url>`, `git push -u origin main`.
3. Optional: get a free Gemini key at aistudio.google.com (Get API key) and add it as a repository secret
   named `GEMINI_API_KEY` (Settings, Secrets and variables, Actions, New repository secret). This step can
   be skipped entirely -- the app works without it, since reading offers no longer depends on Gemini.
   Without a key: everything still works except the one daily "search the web" fallback per mall, and the
   rare page/image the own-made reader can't make sense of just gets a note in the app explaining why,
   instead of an offer.
4. In the repo: Settings, Pages, Source: choose **GitHub Actions**.
5. Open the Actions tab, choose "Refresh offers", click **Run workflow**. Wait about 5 to 10 minutes.
6. Your site is at `https://YOUR-USERNAME.github.io/REPO-NAME/` (also shown in the finished workflow run).
   From now on it refreshes itself every 6 hours.

## Phone app
Open the site link. Android Chrome: menu, "Install app". iPhone Safari: Share, "Add to Home Screen".

## What it costs
Nothing: GitHub Actions and Pages (public repo) are free, Tesseract OCR runs locally in the job for free,
and with the defaults below Gemini is barely used at all -- often zero calls for an entire run.

## How offers are actually found (own-made reader first, Gemini last)
1. **Text pages**: a small rule-based reader (`crawler/heuristics.py`) scans the page's text for real
   discount language (a percentage, "buy 1 get 1", "flat X% off", etc.), figures out the store name from
   the surrounding headings or the line itself, and pulls out dates it can find nearby. No API call.
2. **Promo banner images**: the image is read with Tesseract OCR (`crawler/ocr.py`, runs on the GitHub
   Actions machine, not in the cloud), then the OCR'd text goes through the same rule-based reader.
3. **Only if both of those find nothing** on a page/image that looked like it should have an offer does
   it ask Gemini, and only up to `GEMINI_CALL_CAP` times per run (default 5). Set the `GEMINI_MODE`
   repository variable to `off` to disable Gemini completely, or raise `GEMINI_CALL_CAP` if you'd rather
   it lean on Gemini more.
4. The one daily Google-grounded web search per mall still uses Gemini (there's no own-made replacement
   for "search the whole web"), but it's skipped too when `GEMINI_MODE=off`.
- Page text unchanged since last run: nothing re-read at all.
- Promo image already read: not re-read.
- Expired offers disappear automatically; offers not seen for 10 days disappear too.
- If a key is set, the job picks the newest working Gemini model by itself, so retired model names don't break it.

## When a mall shows no offers
Open the mall in the app and tap "Why nothing here?" -- it now says exactly what happened on each page
(fetch failed, page had almost no text and may need JavaScript, promo images were found but unreadable,
etc.) instead of just staying empty with no explanation.

## Honest limits
- Only the Wakra Ezdan page was checked by hand. Gharaffa and Wukair use the same website template, so they should work.
- Mall of Qatar: only one official page is known and it may be a one-off event page that goes stale between
  sales; the job also tries its sitemap, and (if Gemini is enabled) a daily web search for the rest.
- City Center Doha is the weakest source (no official offers page found). It depends on Google-grounded search,
  so it will show nothing at all if `GEMINI_MODE=off`.
- The rule-based reader is simpler than Gemini: it's tuned to avoid false positives (e.g. "Mall of Qatar offers
  a wide variety of brands" correctly does NOT count as a deal), which means on an unusual page layout it can
  also miss a real offer that a human would spot immediately. Check the "Why nothing here?" notes when that happens.
- Offers posted only on Instagram or WhatsApp are NOT collected (their terms forbid scraping).
- AI (when used) can still misread an image or date. The app labels AI-found results and links the source page;
  keep that label.
- Offers are text and links only. Don't copy mall images or catalogues into the app without permission.
- GitHub pauses scheduled jobs in a repo after 60 days with no activity. The job commits data often, which keeps it alive,
  but if it ever stops, open the Actions tab and click Enable.

## Add a mall
In `sources.json` copy a mall block. `"type":"text"` for pages with written offers, `"type":"images"` for pages of promo banners
(`"context_must"` = a word that appears next to real promo images). `"search": true` adds a daily Google-grounded search.
