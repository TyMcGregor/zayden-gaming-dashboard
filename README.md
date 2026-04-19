# Zayden Gaming — Dashboard

Live, auto-updating YouTube HUD for Zayden's gaming channel ([@ZaydenGaming44](https://www.youtube.com/@ZaydenGaming44)).

Built by the **Boost** sub-agent of Tyler's Nexus assistant.

## What it does
- Shows Zayden's channel as a **game HUD**: player profile, level, XP bar, stat tiles, weekly quests, top mission, achievements.
- Pulls fresh data from the **YouTube Data API v3** every Sunday at 9 PM Pacific.
- Uses **Claude** (Anthropic API) to generate kid-friendly weekly quests in Zayden's voice.
- Hosted free on **GitHub Pages**, built by **GitHub Actions** — no servers to maintain.

## First-time setup
See [`SETUP.md`](./SETUP.md) for the step-by-step guide Tyler needs to run once.

## File layout
```
.
├── .github/workflows/update-dashboard.yml   # Weekly cron + manual trigger
├── assets/                                  # Logo, avatar, favicon
├── scripts/
│   ├── update.py                            # Fetches data, renders dashboard
│   └── requirements.txt
├── templates/
│   └── index.html.j2                        # Jinja2 template
├── index.html                               # Generated output (served by Pages)
├── data.json                                # Snapshot used for week-over-week deltas
├── style.css                                # Gaming-HUD theme
├── script.js                                # Count-up animations, parent toggle
├── SETUP.md                                 # One-time setup guide
└── README.md
```

## Local preview
Just open `index.html` in any browser — the seeded build works with no APIs.

## Manual refresh
Repo → **Actions** tab → **Update Zayden Gaming Dashboard** → **Run workflow**.

## Secrets (set in repo → Settings → Secrets → Actions)
| Name | Where to get it |
|---|---|
| `YOUTUBE_API_KEY` | console.cloud.google.com → YouTube Data API v3 |
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `CHANNEL_ID` | From Zayden's YouTube channel page source (starts with `UC`) |

## Tech
- Python 3.12 · Jinja2 · google-api-python-client · anthropic-sdk
- Pure static HTML/CSS/JS on the frontend — no framework, no build step
- GitHub Actions for the weekly cron and auto-deploy
