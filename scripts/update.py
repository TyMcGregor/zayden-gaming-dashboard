"""
Zayden Gaming dashboard updater.

Runs weekly via GitHub Actions. Fetches public channel metrics from the
YouTube Data API v3, asks Claude Haiku for a fresh batch of kid-friendly
coaching quests, and renders index.html + data.json.
"""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic
from googleapiclient.discovery import build
from jinja2 import Environment, FileSystemLoader, select_autoescape


ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "templates"
OUT_HTML = ROOT / "index.html"
OUT_JSON = ROOT / "data.json"
PREV_JSON = OUT_JSON  # prior snapshot lives at same path before we overwrite

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CHANNEL_ID = os.environ["CHANNEL_ID"]

CLAUDE_MODEL = "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# YouTube data
# ---------------------------------------------------------------------------

def fetch_channel_data():
    yt = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    ch_resp = yt.channels().list(
        id=CHANNEL_ID,
        part="snippet,statistics,contentDetails",
    ).execute()
    if not ch_resp.get("items"):
        raise SystemExit(f"No channel found for CHANNEL_ID={CHANNEL_ID}")
    ch = ch_resp["items"][0]
    uploads_playlist = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    stats = ch["statistics"]

    video_ids = []
    page_token = None
    while len(video_ids) < 50:
        pl = yt.playlistItems().list(
            playlistId=uploads_playlist,
            part="contentDetails",
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for item in pl.get("items", []):
            video_ids.append(item["contentDetails"]["videoId"])
        page_token = pl.get("nextPageToken")
        if not page_token:
            break

    videos = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        v_resp = yt.videos().list(
            id=",".join(chunk),
            part="snippet,statistics,contentDetails",
        ).execute()
        for v in v_resp.get("items", []):
            s = v.get("statistics", {})
            sn = v.get("snippet", {})
            thumbs = sn.get("thumbnails", {})
            thumb = (
                thumbs.get("maxres")
                or thumbs.get("standard")
                or thumbs.get("high")
                or thumbs.get("medium")
                or thumbs.get("default")
                or {"url": ""}
            )["url"]
            videos.append({
                "id": v["id"],
                "title": sn.get("title", ""),
                "published": sn.get("publishedAt", ""),
                "thumbnail": thumb,
                "views": int(s.get("viewCount", 0)),
                "likes": int(s.get("likeCount", 0)),
                "comments": int(s.get("commentCount", 0)),
            })

    return {
        "title": ch["snippet"]["title"],
        "subs": int(stats.get("subscriberCount", 0)),
        "views": int(stats.get("viewCount", 0)),
        "video_count": int(stats.get("videoCount", 0)),
        "videos": videos,
    }


# ---------------------------------------------------------------------------
# Derived computations
# ---------------------------------------------------------------------------

def compute_level(subs: int) -> tuple[int, int, int, float]:
    """Return (level, current_level_floor, next_level_floor, xp_percent)."""
    level = int(math.floor(math.sqrt(max(subs, 0)))) + 1
    current_floor = (level - 1) ** 2
    next_floor = level ** 2
    span = max(next_floor - current_floor, 1)
    xp_pct = max(0.0, min(100.0, (subs - current_floor) / span * 100))
    return level, current_floor, next_floor, xp_pct


def delta(current: float, previous: float | None, unit: str = "") -> tuple[str, str]:
    if previous is None:
        return "", "zero"
    diff = current - previous
    if abs(diff) < 1e-9:
        return "±0 this week", "zero"
    sign = "+" if diff > 0 else "−"
    pretty = f"{sign}{abs(diff):,.0f}{unit} this week"
    cls = "" if diff > 0 else "neg"
    return pretty, cls


def build_achievements(subs: int, views: int, best_views: int) -> list[dict]:
    ypp = min(100.0, subs / 1000 * 100)
    return [
        {"icon": "🎬", "name": "First Upload",       "unlocked": True,             "progress": "UNLOCKED"},
        {"icon": "👣", "name": "First 10 Subs",      "unlocked": subs >= 10,       "progress": f"{min(subs,10)}/10"},
        {"icon": "🥉", "name": "100 Total Views",    "unlocked": views >= 100,     "progress": f"{min(views,100):,}/100"},
        {"icon": "🥈", "name": "1,000 Total Views",  "unlocked": views >= 1000,    "progress": f"{min(views,1000):,}/1,000"},
        {"icon": "🥇", "name": "10,000 Total Views", "unlocked": views >= 10000,   "progress": f"{min(views,10000):,}/10,000"},
        {"icon": "🚀", "name": "First Breakout Hit", "unlocked": best_views >= 500, "progress": f"Best: {best_views:,}"},
        {"icon": "💎", "name": "100 Subs Club",      "unlocked": subs >= 100,      "progress": f"{min(subs,100)}/100"},
        {"icon": "🏆", "name": "YPP Monetization",   "unlocked": subs >= 1000,     "progress": f"{ypp:.1f}% to goal"},
    ]


# ---------------------------------------------------------------------------
# Claude coaching
# ---------------------------------------------------------------------------

COACH_SYSTEM = """You are Boost, a YouTube growth coach for an 11-13 year old
creator named Zayden. His channel is "Zayden Gaming" — he plays Gmod (Star Wars
and FNAF mods are his hits), Brick Rigs, BeamNG, Forza Horizon 5, MechWarrior 5,
Wobbly Life, Stray, Portal, Retro Rewind, and The Last Caretaker. He obscures
his face and keeps his last name, location, school, and friends off camera.

You output JSON ONLY. No prose outside JSON. Voice: encouraging, fun, a
little gamer-slang but not cringey, zero adult jargon. Tips explain WHY they
help in a one-sentence way a kid understands. Never suggest clickbait that
misleads, fear-based thumbnails, or anything that compromises his safety.
Parent summary is a separate short note for Zayden's dad Tyler — more
strategic, references concrete metrics.

Return exactly this JSON shape:
{
  "tagline": "one-line motivating line under his name, under 80 chars",
  "quests": [
    {"icon": "🎯", "title": "QUEST NAME", "body": "what to do in Zayden's voice",
     "why": "short one-sentence why it helps"},
    ... 3 or 4 items total, icons vary from 🎯 ⚡ 🎮 🏆 🚀 💡 🔥 ...
  ],
  "parent_note": "2-3 sentence HTML-safe note to Tyler about the coming week"
}
"""


def coach_with_claude(data: dict, prev: dict | None) -> dict:
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    top5 = sorted(data["videos"], key=lambda v: v["views"], reverse=True)[:5]
    recent5 = sorted(data["videos"], key=lambda v: v["published"], reverse=True)[:5]

    context = {
        "subs": data["subs"],
        "total_views": data["views"],
        "video_count": data["video_count"],
        "subs_delta_week": data["subs"] - prev["subs"] if prev else None,
        "views_delta_week": data["views"] - prev["views"] if prev else None,
        "top_5_videos": [{"title": v["title"], "views": v["views"]} for v in top5],
        "most_recent_5": [{"title": v["title"], "views": v["views"]} for v in recent5],
    }

    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=COACH_SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                "Channel snapshot JSON:\n\n"
                + json.dumps(context, indent=2)
                + "\n\nGenerate this week's dashboard content."
            ),
        }],
    )
    text = msg.content[0].text.strip()
    # Tolerate code fences
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    prev = None
    if PREV_JSON.exists():
        try:
            prev = json.loads(PREV_JSON.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"WARN: prior data.json unreadable: {e}", file=sys.stderr)

    data = fetch_channel_data()

    videos_sorted = sorted(data["videos"], key=lambda v: v["views"], reverse=True)
    top_video = videos_sorted[0] if videos_sorted else None
    recent_videos = sorted(data["videos"], key=lambda v: v["published"], reverse=True)[:10]

    level, cur_floor, next_floor, xp_pct = compute_level(data["subs"])

    # Deltas
    dsubs_text, dsubs_cls = delta(data["subs"], prev["subs"] if prev else None)
    dviews_text, dviews_cls = delta(data["views"], prev["views"] if prev else None)
    dvid_text, dvid_cls = delta(data["video_count"], prev["video_count"] if prev else None)

    # Coaching
    try:
        coach = coach_with_claude(data, prev)
    except Exception as e:
        print(f"WARN: Claude coaching failed ({e}) — using fallback quests", file=sys.stderr)
        coach = {
            "tagline": "Gamer · Creator · Level up every week",
            "quests": [
                {"icon": "🎯", "title": "Quest of the Week",
                 "body": "Record one more Gmod Star Wars video this week — that's your biggest hit!",
                 "why": "YouTube shows more of what's already working."},
                {"icon": "⚡", "title": "Power-Up",
                 "body": "Make your first 15 seconds super exciting — jump straight into the action.",
                 "why": "People decide in the first few seconds whether to keep watching."},
                {"icon": "🎮", "title": "Side Mission",
                 "body": "Reply to every comment this week, even just with an emoji.",
                 "why": "YouTube sees comments as a sign people love your channel."},
            ],
            "parent_note": "Lean into the Gmod Star Wars breakout; shorten edits; reply to comments.",
        }

    # Watch hours — estimate from per-video views * avg duration (no Analytics API)
    # Placeholder 0 until we wire deeper metrics; can be replaced with stored
    # snapshot from analytics CSVs if/when Tyler uploads them.
    watch_hours = round(data["views"] * 0.033, 1)  # rough proxy: ~2min per view
    impressions = "—"
    ctr = "—"
    avd = "—"

    dwatch_text, dwatch_cls = delta(
        watch_hours,
        prev.get("watch_hours") if prev else None,
        unit=" hrs",
    )

    achievements = build_achievements(
        data["subs"], data["views"], top_video["views"] if top_video else 0
    )

    context = {
        "last_updated": datetime.now(timezone.utc).strftime("%a %b %d · %H:%M UTC"),
        "tagline": coach["tagline"],
        "subs": data["subs"],
        "views": data["views"],
        "video_count": data["video_count"],
        "watch_hours": watch_hours,
        "level": level,
        "next_level_subs": next_floor,
        "xp_percent": round(xp_pct, 1),
        "delta_subs_text": dsubs_text, "delta_subs_class": dsubs_cls,
        "delta_views_text": dviews_text, "delta_views_class": dviews_cls,
        "delta_videos_text": dvid_text, "delta_videos_class": dvid_cls,
        "delta_watch_text": dwatch_text, "delta_watch_class": dwatch_cls,
        "quests": coach["quests"],
        "top_video": top_video,
        "recent_videos": recent_videos[:10],
        "achievements": achievements,
        "impressions": impressions,
        "ctr": ctr,
        "avd": avd,
        "ypp_progress": round(min(100.0, data["subs"] / 1000 * 100), 1),
        "parent_note": coach["parent_note"],
    }

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    tpl = env.get_template("index.html.j2")
    OUT_HTML.write_text(tpl.render(**context), encoding="utf-8")

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "subs": data["subs"],
        "views": data["views"],
        "video_count": data["video_count"],
        "watch_hours": watch_hours,
        "top_video_id": top_video["id"] if top_video else None,
        "top_video_views": top_video["views"] if top_video else 0,
    }
    OUT_JSON.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    print(f"OK — subs={data['subs']} views={data['views']} level={level}")


if __name__ == "__main__":
    main()
