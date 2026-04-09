import os
import re
import httpx
from datetime import datetime


APIFY_TOKEN: str = os.getenv("APIFY_API_TOKEN", "")
BASE_URL = "https://api.apify.com/v2/acts"
TIMEOUT = 90


def _normalize_username(username: str) -> str:
    username = username.strip()
    # Handle full TikTok URLs
    match = re.search(r"tiktok\.com/@([^/?&]+)", username)
    if match:
        return match.group(1)
    # Strip leading @
    return username.lstrip("@")


def _parse_date(value) -> str | None:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.utcfromtimestamp(value / 1000).isoformat() + "Z"
        if isinstance(value, str):
            return value
    except Exception:
        pass
    return None


async def scrape_videos(
    username: str,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 30,
) -> list[dict]:
    username = _normalize_username(username)
    if not username:
        raise ValueError("Username must not be empty")
    if not APIFY_TOKEN:
        raise ValueError("APIFY_API_TOKEN is not configured. Add it in Replit Secrets.")

    url = (
        f"{BASE_URL}/clockworks~tiktok-scraper/run-sync-get-dataset-items"
        f"?token={APIFY_TOKEN}&timeout={TIMEOUT}&memory=512"
    )
    body = {
        "profiles": [f"https://www.tiktok.com/@{username}"],
        "resultsPerPage": limit,
    }

    async with httpx.AsyncClient(timeout=TIMEOUT + 10) as client:
        resp = await client.post(url, json=body)
        if resp.status_code not in (200, 201):
            raise ValueError(
                f"Apify returned status {resp.status_code}: {resp.text[:300]}"
            )
        items = resp.json()

    if not isinstance(items, list):
        raise ValueError(f"Unexpected Apify response format: {str(items)[:200]}")

    videos = []
    for item in items:
        published_raw = (
            item.get("createTimeISO")
            or item.get("createTime")
            or item.get("created")
            or item.get("timestamp")
        )
        published = _parse_date(published_raw)

        # Date filtering
        if date_from and published:
            try:
                pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                from_dt = datetime.fromisoformat(date_from)
                if from_dt.tzinfo is None:
                    from_dt = from_dt.replace(tzinfo=pub_dt.tzinfo)
                if pub_dt < from_dt:
                    continue
            except Exception:
                pass

        if date_to and published:
            try:
                pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                to_dt = datetime.fromisoformat(date_to)
                if to_dt.tzinfo is None:
                    to_dt = to_dt.replace(tzinfo=pub_dt.tzinfo)
                if pub_dt > to_dt:
                    continue
            except Exception:
                pass

        duration_raw = item.get("videoMeta", {}).get("duration") if item.get("videoMeta") else item.get("duration")
        try:
            duration = int(duration_raw) if duration_raw is not None else 0
        except (ValueError, TypeError):
            duration = 0

        stats = item.get("stats", {}) or {}

        videos.append({
            "id": item.get("id") or item.get("webVideoUrl", "").split("/")[-1],
            "url": item.get("webVideoUrl") or item.get("url") or "",
            "thumbnail": (
                item.get("videoMeta", {}).get("coverUrl")
                if item.get("videoMeta")
                else item.get("thumbnail") or item.get("covers", [None])[0]
            ) or "",
            "published": published or "",
            "duration": duration,
            "views": stats.get("playCount") or item.get("playCount") or 0,
            "likes": stats.get("diggCount") or item.get("diggCount") or 0,
            "comments": stats.get("commentCount") or item.get("commentCount") or 0,
            "shares": stats.get("shareCount") or item.get("shareCount") or 0,
            "caption": item.get("text") or item.get("desc") or item.get("description") or "",
        })

    return videos


async def scrape_comments(video_url: str, count: int = 50) -> list[dict]:
    if not video_url:
        raise ValueError("Video URL must not be empty")
    if not APIFY_TOKEN:
        raise ValueError("APIFY_API_TOKEN is not configured. Add it in Replit Secrets.")

    run_url = (
        f"{BASE_URL}/clockworks~tiktok-scraper/run-sync-get-dataset-items"
        f"?token={APIFY_TOKEN}&timeout={TIMEOUT}&memory=512"
    )
    body = {
        "postURLs": [video_url],
        "commentsPerPost": count,
    }

    async with httpx.AsyncClient(timeout=TIMEOUT + 10) as client:
        resp = await client.post(run_url, json=body)
        if resp.status_code not in (200, 201):
            raise ValueError(
                f"Apify returned status {resp.status_code}: {resp.text[:300]}"
            )
        items = resp.json()

        if not isinstance(items, list) or not items:
            raise ValueError("No data returned from Apify for that video URL.")

        # Comments are stored in a separate linked dataset
        comments_dataset_url = items[0].get("commentsDatasetUrl", "")
        if not comments_dataset_url:
            raise ValueError(
                "Apify did not return a comments dataset URL. "
                "The video may have comments disabled or the actor may not support comment scraping for this URL."
            )

        # Fetch comments from the linked dataset (append token)
        sep = "&" if "?" in comments_dataset_url else "?"
        comments_url = f"{comments_dataset_url}{sep}token={APIFY_TOKEN}&limit={count}"
        cresp = await client.get(comments_url)
        if cresp.status_code != 200:
            raise ValueError(
                f"Failed to fetch comments dataset: status {cresp.status_code}"
            )
        raw_comments = cresp.json()

    if not isinstance(raw_comments, list):
        raise ValueError(f"Unexpected comments format: {str(raw_comments)[:200]}")

    comments = []
    for item in raw_comments:
        posted_raw = item.get("createTimeISO") or item.get("createTime")
        posted = _parse_date(posted_raw)

        comments.append({
            "id": item.get("cid") or item.get("id") or "",
            "username": item.get("uniqueId") or item.get("uid") or "",
            "avatar": item.get("avatarThumbnail") or item.get("avatarThumb") or "",
            "text": item.get("text") or item.get("comment") or "",
            "likes": item.get("diggCount") or 0,
            "replies": item.get("replyCommentTotal") or 0,
            "posted": posted or "",
        })

    return comments
