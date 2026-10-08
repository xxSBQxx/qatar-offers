# Qatar Offers: fully automatic version

Every 6 hours a free robot (GitHub Actions) reads the malls' official pages, lets Gemini turn text and promo images
into offers, saves them, and republishes the website. You do nothing after setup. The website also installs on phones.

Covers 3 test malls: Mall of Qatar, City Center Doha, Ezdan Mall (Gharaffa, Wakra, Wukair). Edit `sources.json` to add more.

## Setup (about 15 minutes, once)
1. Create a free account at github.com. Create a **new public repository** (for example `qatar-offers`).
   (Public is required for free GitHub Pages hosting. Your Gemini key stays secret.)
2. Upload this folder's contents to the repository.
   - Easy way: on the repo page click "uploading an existing file" and drag in everything (include the `.github` folder).
     On a Mac press Cmd+Shift+. in Finder to show it. Check the repo afterwards shows `.github/workflows/refresh.yml`.
   - Or with git: `git init`, `git add .`, `git commit -m start`, `git branch -M main`, `git remote add origin <repo-url>`, `git push -u origin main`.
3. Get a free Gemini key at aistudio.google.com (Get API key).
   In the repo: Settings, Secrets and variables, Actions, New repository secret. Name: `GEMINI_API_KEY`, value: your key.
4. In the repo: Settings, Pages, Source: choose **GitHub Actions**.
5. Open the Actions tab, choose "Refresh offers", click **Run workflow**. Wait about 5 to 10 minutes.
6. Your site is at `https://YOUR-USERNAME.github.io/REPO-NAME/` (also shown in the finished workflow run).
   From now on it refreshes itself every 6 hours.

## Phone app
Open the site link. Android Chrome: menu, "Install app". iPhone Safari: Share, "Add to Home Screen".

## What it costs
Nothing, as long as free tiers last: GitHub Actions and Pages (public repo), Gemini free tier with the cheapest Flash-Lite model.
Each promo image or page is read once and remembered, so repeat runs make almost no AI calls.
If Gemini's free limit ever changes, costs would be cents per month at this size.

## How it avoids wasted AI calls
- Page text unchanged since last run: no AI call.
- Promo image already read: no AI call.
- Google-grounded search: at most once a day per mall.
- Expired offers disappear automatically; offers not seen for 10 days disappear too.
- The job picks the newest working Gemini model by itself, so retired model names don't break it.

## Honest limits
- **Not run against the live sites and Gemini yet.** The logic passes offline tests; the first Actions run is the real test.
  Check the run log in the Actions tab; paste me any error.
- Only the Wakra Ezdan page was checked by hand. Gharaffa and Wukair use the same website template, so they should work.
- Mall of Qatar: only one official page is known; the job also tries its sitemap, and relies on Google search for the rest.
- City Center Doha is the weakest source (no official offers page found). It depends on Google-grounded search.
- Offers posted only on Instagram or WhatsApp are NOT collected (their terms forbid scraping).
- AI can misread an image or date. The app labels results as AI-found and links the source page; keep that label.
- Offers are text and links only. Don't copy mall images or catalogues into the app without permission.
- GitHub pauses scheduled jobs in a repo after 60 days with no activity. The job commits data often, which keeps it alive,
  but if it ever stops, open the Actions tab and click Enable.
- Free-tier rules change. Recheck ai.google.dev pricing now and then.

## Add a mall
In `sources.json` copy a mall block. `"type":"text"` for pages with written offers, `"type":"images"` for pages of promo banners
(`"context_must"` = a word that appears next to real promo images). `"search": true` adds a daily Google-grounded search.
