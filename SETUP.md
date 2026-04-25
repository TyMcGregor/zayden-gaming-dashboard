# Zayden Gaming Dashboard — Setup Guide

Follow these steps once. After that the site is fully automatic — it refreshes itself every **Sunday, Wednesday, and Friday night** and you never have to touch it again.

**Estimated time:** 20–30 minutes, most of it waiting on page loads.

---

## What you'll end up with
- A live URL (e.g., `https://<yourname>.github.io/zayden-gaming-dashboard/`) that Zayden can bookmark
- Stats, milestones, monetization progress, comments, quests, and pep-talk refresh automatically Sun / Wed / Fri at ~9 PM Pacific
- Zero servers, zero monthly cost (GitHub Pages + Actions are free for this)

---

## Step 1 — Create a GitHub account (5 min)

1. Go to **https://github.com/signup**
2. Enter your email, create a password, pick a username (this becomes part of your dashboard URL — e.g., `tyler-nexus`)
3. Verify your email
4. Free plan is all you need — skip the paid tiers

---

## Step 2 — Install GitHub Desktop (easiest path for pushing files) (5 min)

1. Go to **https://desktop.github.com**
2. Download and install GitHub Desktop
3. Sign in with the account you just made

> *Alternative:* if you prefer the command line you can use `git` directly — see the "Command-line path" section at the bottom.

---

## Step 3 — Create the repository (3 min)

1. On github.com, click the **+** icon top right → **New repository**
2. Repository name: `zayden-gaming-dashboard`
3. Description: `Zayden's YouTube channel dashboard` (optional)
4. Visibility: **Private** ← important
5. **DO NOT** check "Add a README" — leave all init boxes unchecked
6. Click **Create repository**
7. Leave this page open — you'll need the URL in a minute

---

## Step 4 — Get a YouTube Data API key (5 min)

1. Go to **https://console.cloud.google.com**
2. Sign in with your Google account
3. Top bar → project dropdown → **New Project** → name it `Zayden Dashboard` → Create
4. Once created, select the project
5. Left menu → **APIs & Services** → **Library**
6. Search for **"YouTube Data API v3"** → click it → **Enable**
7. Left menu → **APIs & Services** → **Credentials**
8. **+ Create Credentials** → **API key**
9. Copy the key that pops up — **save it somewhere safe**, you'll need it in Step 6
10. (Optional but recommended) Click the key you just made → **Restrict key** → under "API restrictions" select **YouTube Data API v3** → Save

---

## Step 5 — Find Zayden's Channel ID (2 min)

Easiest way:
1. Go to **https://www.youtube.com/@ZaydenGaming44**
2. Right-click the page → **View Page Source** (Ctrl+U)
3. Ctrl+F and search for `channel_id=` or `"channelId":"`
4. Copy the ID — it starts with **UC** and is 24 characters long (e.g., `UCxxxxxxxxxxxxxxxxxxxxxx`)

Save this ID — you need it in Step 6.

---

## Step 6 — Add your secrets to GitHub (3 min)

You'll need 3 things ready:
- `YOUTUBE_API_KEY` from Step 4
- `CHANNEL_ID` from Step 5
- `ANTHROPIC_API_KEY` — get this at **https://console.anthropic.com** → API Keys → Create Key (you likely already have one, since you use Claude Code)

Now add them to the repo:
1. On github.com, open your `zayden-gaming-dashboard` repo
2. **Settings** tab → left sidebar → **Secrets and variables** → **Actions**
3. Click **New repository secret** for each:
   - Name: `YOUTUBE_API_KEY` — Value: (paste the key) → **Add secret**
   - Name: `ANTHROPIC_API_KEY` — Value: (paste the key) → **Add secret**
   - Name: `CHANNEL_ID` — Value: (paste the channel ID starting with UC) → **Add secret**

---

## Step 7 — Enable GitHub Pages (1 min)

1. In the repo, **Settings** tab → left sidebar → **Pages**
2. Under "Build and deployment" → **Source** → select **GitHub Actions**
3. That's it. No save button — it auto-applies.

---

## Step 8 — Push the dashboard files to the repo (5 min)

### Using GitHub Desktop (recommended):

1. Open GitHub Desktop
2. **File** → **Add Local Repository**
3. Choose folder: `C:\Users\tygre\Desktop\Claude Home\output\dashboards\zayden-gaming`
4. GitHub Desktop will say "this isn't a repository" → click **create a repository** in the warning text
5. In the dialog: Name stays `zayden-gaming`, leave defaults, click **Create repository**
6. Top of window → **Publish repository** button
7. Dialog appears → **UNCHECK "Keep this code private"** ... wait, actually DO keep it private (it re-prompts because you're pushing new). Keep the "Keep this code private" box **CHECKED**
8. Change the name to `zayden-gaming-dashboard` to match what you created on github.com
9. Click **Publish Repository**

   > If GitHub Desktop complains that the name is taken on github.com, that's because you pre-created the repo in Step 3. Instead:
   > - In GitHub Desktop: **Repository** menu → **Repository settings** → **Remote** tab
   > - Paste the URL from your github.com repo page (ends in `.git`) → Save
   > - Then **Push origin** button

### What you should see after pushing:
- Refresh your repo page on github.com
- You should see: `.github/`, `assets/`, `scripts/`, `templates/`, `index.html`, `style.css`, `script.js`, `data.json`, `README.md`, `SETUP.md`

---

## Step 9 — Trigger the first build (1 min)

1. On the repo page, click the **Actions** tab
2. Left sidebar → click **Update Zayden Gaming Dashboard**
3. Right side → **Run workflow** dropdown → **Run workflow** (green button)
4. Wait about 60 seconds — the job should turn green with a checkmark
5. If it fails: click the red X to see what went wrong (99% of the time it's a typo in one of the 3 secrets — fix it in Settings → Secrets and re-run)

---

## Step 10 — Visit the live dashboard! 🎮

After the Action finishes green:

- URL: **`https://<your-github-username>.github.io/zayden-gaming-dashboard/`**
- Example: if your username is `tyler-nexus`, the URL is `https://tyler-nexus.github.io/zayden-gaming-dashboard/`
- Bookmark it for Zayden
- It may take 1–2 minutes after the first Action for the URL to become reachable

---

## From now on — automatic

- Every **Sunday, Wednesday, and Friday at ~9 PM Pacific** (GitHub cron drifts by a few min) the Action runs
- Pulls fresh YouTube stats + the 5 latest comments → asks Claude for new quests + a pep-talk → updates the page
- You don't have to do anything. Ever.

---

## Optional: Custom domain (e.g., zaydengaming.com) — $12/yr

Skip this for now unless Zayden really wants a custom URL.

1. Buy the domain from Namecheap or Cloudflare
2. In the repo: **Settings** → **Pages** → **Custom domain** → enter `zaydengaming.com` → Save
3. At your domain registrar, add a CNAME record pointing to `<your-username>.github.io`
4. Wait a few min for DNS → check the "Enforce HTTPS" box

---

## Troubleshooting

**Action fails with `Channel not found`** → Your `CHANNEL_ID` is wrong. Re-do Step 5 carefully — it must start with `UC` and be 24 chars.

**Action fails with `API key not valid`** → Either the `YOUTUBE_API_KEY` secret has a typo, or you didn't enable the YouTube Data API v3 in Step 4.6.

**Action fails with `anthropic ... 401`** → `ANTHROPIC_API_KEY` is invalid or expired. Regenerate at console.anthropic.com.

**Page loads but shows no images** → wait a minute; GitHub Pages takes a moment to publish asset files on first push.

**Want to test-run locally before pushing?** Just open `index.html` in your browser — the seeded version works with no APIs needed.

---

## Command-line path (only if you skipped GitHub Desktop)

```bash
cd "C:/Users/tygre/Desktop/Claude Home/output/dashboards/zayden-gaming"
git init
git add .
git commit -m "initial dashboard"
git branch -M main
git remote add origin https://github.com/<your-username>/zayden-gaming-dashboard.git
git push -u origin main
```

---

Questions or issues? Come back to me (Claude) and I'll walk through anything.
