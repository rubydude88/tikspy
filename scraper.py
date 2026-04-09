import re
import httpx
from datetime import datetime


BASE_URL = "https://api.apify.com/v2/acts"
TIMEOUT = 90


def _normalize_username(username: str) -> str:
    username = username.strip()
    match = re.search(r"tiktok\.com/@([^/?&]+)", username)
    if match:
        return match.group(1)
    return username.lstrip("@")


def _parse_date(value) -> str | None:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            ts = value / 1000 if value > 1e10 else value
            return datetime.utcfromtimestamp(ts).isoformat() + "Z"
        if isinstance(value, str):
            return value
    except Exception:
        pass
    return None


async def scrape_videos(
    api_key: str,
    username: str,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 30,
) -> list[dict]:
    username = _normalize_username(username)
    if not username:
        raise ValueError("Username must not be empty")
    if not api_key:
        raise ValueError("API key is required")

    url = (
        f"{BASE_URL}/clockworks~tiktok-scraper/run-sync-get-dataset-items"
        f"?token={api_key}&timeout={TIMEOUT}&memory=512"
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


async def scrape_comments(api_key: str, video_url: str, count: int = 50) -> list[dict]:
    if not video_url:
        raise ValueError("Video URL must not be empty")
    if not api_key:
        raise ValueError("API key is required")

    run_url = (
        f"{BASE_URL}/clockworks~tiktok-scraper/run-sync-get-dataset-items"
        f"?token={api_key}&timeout={TIMEOUT}&memory=512"
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

        print("DEBUG scrape_comments — items[0] keys:", list(items[0].keys()))

        comments_dataset_url = (
            items[0].get("commentsDatasetUrl")
            or items[0].get("commentsDatasetId")
            or items[0].get("commentsData")
            or items[0].get("datasetUrl")
        )

        if comments_dataset_url:
            sep = "&" if "?" in comments_dataset_url else "?"
            comments_url = f"{comments_dataset_url}{sep}token={api_key}&limit={count}"
            cresp = await client.get(comments_url)
            if cresp.status_code != 200:
                raise ValueError(
                    f"Failed to fetch comments dataset: status {cresp.status_code}"
                )
            raw_comments = cresp.json()
        else:
            raw_comments = (
                items[0].get("latestComments")
                or items[0].get("comments")
                or []
            )
            if not raw_comments:
                raise ValueError(
                    "Apify did not return any comments data. "
                    "The video may have comments disabled, or the actor version "
                    "may not support comment scraping for this URL. "
                    "Check server logs for the available response keys."
                )

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


async def scrape_replies(api_key: str, video_url: str, comment_id: str, count: int = 20) -> list[dict]:
    if not video_url:
        raise ValueError("Video URL must not be empty")
    if not comment_id:
        raise ValueError("Comment ID must not be empty")
    if not api_key:
        raise ValueError("API key is required")

    run_url = (
        f"{BASE_URL}/clockworks~tiktok-scraper/run-sync-get-dataset-items"
        f"?token={api_key}&timeout={TIMEOUT}&memory=512"
    )
    body = {
        "postURLs": [video_url],
        "commentsPerPost": 0,
        "repliesPerComment": count,
        "commentIds": [comment_id],
    }

    async with httpx.AsyncClient(timeout=TIMEOUT + 10) as client:
        resp = await client.post(run_url, json=body)
        if resp.status_code not in (200, 201):
            raise ValueError(
                f"Apify returned status {resp.status_code}: {resp.text[:300]}"
            )
        items = resp.json()

        if not isinstance(items, list) or not items:
            raise ValueError("No data returned from Apify for replies.")

        print("DEBUG scrape_replies — items[0] keys:", list(items[0].keys()))

        replies_dataset_url = (
            items[0].get("repliesDatasetUrl")
            or items[0].get("commentsDatasetUrl")
            or items[0].get("datasetUrl")
        )

        if replies_dataset_url:
            sep = "&" if "?" in replies_dataset_url else "?"
            replies_url = f"{replies_dataset_url}{sep}token={api_key}&limit={count}"
            rresp = await client.get(replies_url)
            if rresp.status_code != 200:
                raise ValueError(
                    f"Failed to fetch replies dataset: status {rresp.status_code}"
                )
            raw_replies = rresp.json()
        else:
            raw_replies = (
                items[0].get("replies")
                or items[0].get("latestComments")
                or []
            )
            if not raw_replies:
                raise ValueError(
                    "Apify did not return any replies data. "
                    "Check server logs for the available response keys."
                )

    if not isinstance(raw_replies, list):
        raise ValueError(f"Unexpected replies format: {str(raw_replies)[:200]}")

    replies = []
    for item in raw_replies:
        posted_raw = item.get("createTimeISO") or item.get("createTime")
        posted = _parse_date(posted_raw)
        replies.append({
            "id": item.get("cid") or item.get("id") or "",
            "username": item.get("uniqueId") or item.get("uid") or "",
            "avatar": item.get("avatarThumbnail") or item.get("avatarThumb") or "",
            "text": item.get("text") or item.get("comment") or "",
            "likes": item.get("diggCount") or 0,
            "posted": posted or "",
        })

    return replies
