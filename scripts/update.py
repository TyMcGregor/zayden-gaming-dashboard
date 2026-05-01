"""
Zayden Gaming dashboard updater.

Runs weekly via GitHub Actions. Fetches public channel metrics from the
YouTube Data API v3, asks Claude Haiku for a fresh batch of kid-friendly
coaching quests, and renders index.html + data.json.
"""

from __future__ import annotations

import html
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anthropic import Anthropic
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from jinja2 import Environment, FileSystemLoader, select_autoescape


ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "templates"
OUT_HTML = ROOT / "index.html"
OUT_JSON = ROOT / "data.json"
PREV_JSON = OUT_JSON  # prior snapshot lives at same path before we overwrite
WEEKLY_HISTORY = ROOT / "weekly_history.json"  # rolling snapshots for 7-day deltas
WEEKLY_HISTORY_CAP = 14  # ~1 month at 3 runs/week

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


def delta(current: float, week_ago: float | None, unit: str = "") -> tuple[str, str]:
    """Format the change from a value ~7 days ago. Returns (text, css_class)."""
    if week_ago is None:
        return "new baseline", "zero"
    diff = current - week_ago
    if abs(diff) < 1e-9:
        return f"±0{unit} this week", "zero"
    sign = "+" if diff > 0 else "−"
    pretty = f"{sign}{abs(diff):,.0f}{unit} this week"
    cls = "" if diff > 0 else "neg"
    return pretty, cls


def load_weekly_history() -> list[dict]:
    if not WEEKLY_HISTORY.exists():
        return []
    try:
        return json.loads(WEEKLY_HISTORY.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"WARN: weekly_history.json unreadable ({e}) — starting fresh", file=sys.stderr)
        return []


def find_week_ago_snapshot(history: list[dict], now: datetime) -> dict | None:
    """Pick the snapshot closest to 7 days before `now`, but only if it is
    at least 5 days old. Otherwise return None so the UI shows 'new baseline'
    instead of inventing a tiny delta from a 1-2 day gap."""
    if not history:
        return None
    target = now - timedelta(days=7)
    min_age = timedelta(days=5)
    candidates = []
    for s in history:
        try:
            ts = datetime.fromisoformat(s["generated_at"].replace("Z", "+00:00"))
        except Exception:
            continue
        if (now - ts) >= min_age:
            candidates.append((abs((ts - target).total_seconds()), s))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


# Round numbers Zayden recognizes — used for "next milestone" tiles
SUB_MILESTONES =  [25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 1000000]
VIEW_MILESTONES = [1000, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000, 5000000, 10000000]


def next_milestone(value: int, ladder: list[int]) -> int:
    for m in ladder:
        if value < m:
            return m
    return ladder[-1]


def fmt_int(n: int | float) -> str:
    n = int(n)
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n/1_000:.1f}K".replace(".0K", "K")
    return f"{n:,}"


def humanize_relative(iso_ts: str) -> str:
    """Turn an ISO timestamp into 'just now', '3 hours ago', '2 days ago'."""
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return ""
    now = datetime.now(timezone.utc)
    secs = max(0, int((now - ts).total_seconds()))
    if secs < 60:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins} min ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs} hr{'s' if hrs != 1 else ''} ago"
    days = hrs // 24
    if days < 14:
        return f"{days} day{'s' if days != 1 else ''} ago"
    weeks = days // 7
    if weeks < 9:
        return f"{weeks} wk{'s' if weeks != 1 else ''} ago"
    months = days // 30
    if months < 12:
        return f"{months} mo ago"
    return f"{days // 365} yr ago"


_TAG_RE = re.compile(r"<[^>]+>")


def clean_comment_text(raw: str, limit: int = 180) -> str:
    """Strip HTML tags YouTube returns in textDisplay, decode entities, truncate."""
    text = _TAG_RE.sub("", raw or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _comment_thread_to_dict(item: dict, video_titles: dict[str, str]) -> dict:
    top = item.get("snippet", {}).get("topLevelComment", {})
    sn = top.get("snippet", {})
    video_id = sn.get("videoId") or item.get("snippet", {}).get("videoId", "")
    comment_id = top.get("id") or item.get("id", "")
    return {
        "id": comment_id,
        "author": sn.get("authorDisplayName", "Viewer"),
        "author_url": sn.get("authorChannelUrl", ""),
        "text": clean_comment_text(sn.get("textDisplay", "")),
        "video_id": video_id,
        "video_title": video_titles.get(video_id, "a video"),
        "published": sn.get("publishedAt", ""),
        "relative": humanize_relative(sn.get("publishedAt", "")),
        "url": (
            f"https://www.youtube.com/watch?v={video_id}&lc={comment_id}"
            if video_id and comment_id else
            f"https://www.youtube.com/watch?v={video_id}" if video_id else "#"
        ),
        "likes": int(sn.get("likeCount", 0)),
    }


def _http_error_reason(e: HttpError) -> str:
    """Pull the YouTube API error reason out of an HttpError, e.g. 'commentsDisabled'."""
    try:
        body = json.loads(e.content.decode("utf-8") if isinstance(e.content, bytes) else e.content)
        errs = body.get("error", {}).get("errors", [])
        return errs[0].get("reason", "") if errs else ""
    except Exception:
        return ""


def fetch_recent_comments(yt, channel_id: str, recent_videos: list[dict], video_titles: dict[str, str], n: int = 5) -> list[dict]:
    """Pull the N most recent top-level comments across the channel.

    YouTube removed the `allThreadsRelatedToChannel` parameter from
    commentThreads.list, so we poll the channel's most recent videos directly
    and merge results. Costs one quota unit per video polled.

    Per-video errors are logged but do not fail the run. Only a true catastrophic
    error (e.g. all videos return auth errors) results in an empty list.
    """
    videos_by_recent = sorted(recent_videos, key=lambda v: v.get("published", ""), reverse=True)[:8]
    items: list[dict] = []
    seen_ids: set[str] = set()
    polled = 0
    errors = 0

    for v in videos_by_recent:
        vid = v.get("id")
        if not vid:
            continue
        polled += 1
        try:
            resp = yt.commentThreads().list(
                part="snippet",
                videoId=vid,
                order="time",
                maxResults=5,
                textFormat="html",
            ).execute()
        except HttpError as e:
            reason = _http_error_reason(e)
            if reason == "commentsDisabled":
                continue  # legitimate, not an error
            errors += 1
            print(f"WARN: comment fetch failed for video {vid} (status={e.resp.status} reason={reason!r})", file=sys.stderr)
            continue
        for it in resp.get("items", []):
            cid = it.get("id", "")
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            items.append(it)

    print(f"INFO: comments polled {polled} video(s), {errors} error(s), collected {len(items)} comment(s)", file=sys.stderr)

    # Convert + sort by publishedAt desc, take top n.
    out = [_comment_thread_to_dict(it, video_titles) for it in items]
    out.sort(key=lambda c: c.get("published", ""), reverse=True)
    return out[:n]


def build_monetization(subs: int, watch_hours: float) -> dict:
    """Two YPP tiers as kid-friendly progress data."""
    shorts_pct = round(min(100.0, subs / 500 * 100), 1)
    ypp_subs_pct = round(min(100.0, subs / 1000 * 100), 1)
    ypp_hours_pct = round(min(100.0, watch_hours / 4000 * 100), 1)
    return {
        "shorts_tier": {
            "name": "Shorts Monetization",
            "subs_pct": shorts_pct,
            "subs_current": subs,
            "subs_target": 500,
            "subs_remaining": max(0, 500 - subs),
            "note": "Also needs 3 million Shorts views in the last 90 days.",
            "unlocked": subs >= 500,
        },
        "full_ypp": {
            "name": "Full Partner Program",
            "subs_pct": ypp_subs_pct,
            "subs_current": subs,
            "subs_target": 1000,
            "subs_remaining": max(0, 1000 - subs),
            "hours_pct": ypp_hours_pct,
            "hours_current": round(watch_hours, 1),
            "hours_target": 4000,
            "hours_remaining": max(0, round(4000 - watch_hours, 1)),
            "unlocked": subs >= 1000 and watch_hours >= 4000,
        },
    }


PEP_TALK_SYSTEM = """You are Boost, a hype coach for Zayden (age 12), a YouTube
gamer. Write ONE upbeat, age-appropriate sentence — max 20 words — that
celebrates whichever metric moved the most since last update. No emojis at the
start. No exclamation overload (max one !). No fake numbers — only mention
numbers from the JSON. If everything is 0 or negative, give honest gentle
encouragement about consistency. Output the sentence text only, no quotes."""


def generate_pep_talk(client: Anthropic, deltas: dict) -> str:
    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=120,
            system=PEP_TALK_SYSTEM,
            messages=[{
                "role": "user",
                "content": "Deltas since last update:\n" + json.dumps(deltas, indent=2),
            }],
        )
        return msg.content[0].text.strip().strip('"').strip("'")
    except Exception as e:
        print(f"WARN: pep-talk generation failed ({e})", file=sys.stderr)
        return "Every upload is a level-up — keep showing up and the numbers will follow."


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

    # Comments — use the videos we already pulled to map id -> title
    yt = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    title_lookup = {v["id"]: v["title"] for v in data["videos"]}
    recent_comments = fetch_recent_comments(yt, CHANNEL_ID, data["videos"], title_lookup, n=5)

    level, cur_floor, next_floor, xp_pct = compute_level(data["subs"])

    # Weekly deltas: compare against snapshot ~7 days old, not the prior run.
    now_utc = datetime.now(timezone.utc)
    history = load_weekly_history()
    week_ago = find_week_ago_snapshot(history, now_utc)
    dsubs_text, dsubs_cls = delta(data["subs"], week_ago["subs"] if week_ago else None)
    dviews_text, dviews_cls = delta(data["views"], week_ago["views"] if week_ago else None)
    dvid_text, dvid_cls = delta(data["video_count"], week_ago["video_count"] if week_ago else None)

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
        week_ago.get("watch_hours") if week_ago else None,
        unit=" hrs",
    )

    achievements = build_achievements(
        data["subs"], data["views"], top_video["views"] if top_video else 0
    )

    # Monetization + next-up milestone tiles
    monetization = build_monetization(data["subs"], watch_hours)
    sub_goal = next_milestone(data["subs"], SUB_MILESTONES)
    view_goal = next_milestone(data["views"], VIEW_MILESTONES)
    milestones = {
        "sub_goal": sub_goal,
        "subs_to_go": max(0, sub_goal - data["subs"]),
        "subs_pct": round(min(100.0, data["subs"] / sub_goal * 100), 1) if sub_goal else 100.0,
        "sub_goal_label": fmt_int(sub_goal),
        "view_goal": view_goal,
        "views_to_go": max(0, view_goal - data["views"]),
        "views_pct": round(min(100.0, data["views"] / view_goal * 100), 1) if view_goal else 100.0,
        "view_goal_label": fmt_int(view_goal),
    }

    # Coach pep-talk based on deltas (gracefully handles no-prior-snapshot case)
    pep_deltas = {
        "subs_change": data["subs"] - prev["subs"] if prev else 0,
        "views_change": data["views"] - prev["views"] if prev else 0,
        "videos_change": data["video_count"] - prev["video_count"] if prev else 0,
        "watch_hours_change": round(watch_hours - prev["watch_hours"], 1) if prev and "watch_hours" in prev else 0,
        "current_subs": data["subs"],
        "current_views": data["views"],
        "subs_to_next_milestone": milestones["subs_to_go"],
        "next_milestone": sub_goal,
    }
    pep_talk = generate_pep_talk(Anthropic(api_key=ANTHROPIC_API_KEY), pep_deltas)

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
        "monetization": monetization,
        "milestones": milestones,
        "pep_talk": pep_talk,
        "recent_comments": recent_comments,
    }

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    tpl = env.get_template("index.html.j2")
    OUT_HTML.write_text(tpl.render(**context), encoding="utf-8")

    snapshot = {
        "generated_at": now_utc.isoformat(),
        "subs": data["subs"],
        "views": data["views"],
        "video_count": data["video_count"],
        "watch_hours": watch_hours,
        "top_video_id": top_video["id"] if top_video else None,
        "top_video_views": top_video["views"] if top_video else 0,
        "monetization": monetization,
        "milestones": milestones,
        "pep_talk": pep_talk,
        "recent_comments": recent_comments,
    }
    OUT_JSON.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    # Append a lean snapshot to weekly_history.json (capped) so future runs can
    # compute true 7-day deltas instead of "since last run" deltas.
    history.append({
        "generated_at": now_utc.isoformat(),
        "subs": data["subs"],
        "views": data["views"],
        "video_count": data["video_count"],
        "watch_hours": watch_hours,
    })
    history = history[-WEEKLY_HISTORY_CAP:]
    WEEKLY_HISTORY.write_text(json.dumps(history, indent=2), encoding="utf-8")

    print(f"OK — subs={data['subs']} views={data['views']} level={level}")


if __name__ == "__main__":
    main()
