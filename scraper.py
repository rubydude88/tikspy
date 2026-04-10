import re
import httpx
from datetime import datetime, timezone


BASE_URL = "https://api.apify.com/v2/acts"
TIMEOUT = 90

# How many videos to fetch per Apify call when paginating for date range.
_PAGE_SIZE = 30
_MAX_CRAWL = 300


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


def _parse_dt(value: str | None):
    """Parse supported date formats into UTC timezone-aware datetime."""
    if not value:
        return None

    try:
        s = str(value).strip()

        # Support dd/mm/yyyy from frontend
        if re.match(r"^\d{2}/\d{2}/\d{4}$", s):
            dt = datetime.strptime(s, "%d/%m/%Y")
            return dt.replace(tzinfo=timezone.utc)

        # Support yyyy-mm-dd
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            dt = datetime.strptime(s, "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)

        # Support ISO strings, with or without timezone
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))

        # If naive, force UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        return None


def _item_to_video(item: dict) -> dict:
    published_raw = (
        item.get("createTimeISO")
        or item.get("createTime")
        or item.get("created")
        or item.get("timestamp")
    )
    published = _parse_date(published_raw)

    duration_raw = (
        item.get("videoMeta", {}).get("duration")
        if item.get("videoMeta")
        else item.get("duration")
    )
    try:
        duration = int(duration_raw) if duration_raw is not None else 0
    except (ValueError, TypeError):
        duration = 0

    stats = item.get("stats", {}) or {}

    return {
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
    }


async def _fetch_page(client: httpx.AsyncClient, api_key: str, username: str, page_size: int) -> list[dict]:
    url = (
        f"{BASE_URL}/clockworks~tiktok-scraper/run-sync-get-dataset-items"
        f"?token={api_key}&timeout={TIMEOUT}&memory=512"
    )
    body = {
        "profiles": [f"https://www.tiktok.com/@{username}"],
        "resultsPerPage": page_size,
    }
    resp = await client.post(url, json=body)
    if resp.status_code not in (200, 201):
        raise ValueError(f"Apify returned status {resp.status_code}: {resp.text[:300]}")
    items = resp.json()
    if not isinstance(items, list):
        raise ValueError(f"Unexpected Apify response format: {str(items)[:200]}")
    return items


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

    from_dt = _parse_dt(date_from) if date_from else None
    to_dt = _parse_dt(date_to) if date_to else None

    # Make date_to inclusive until end of day
    if date_to:
        s = str(date_to).strip()
        if re.match(r"^\d{2}/\d{2}/\d{4}$", s) or re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            if to_dt:
                to_dt = to_dt.replace(hour=23, minute=59, second=59, microsecond=999999)

    # No date filter: simple fetch
    if not from_dt and not to_dt:
        async with httpx.AsyncClient(timeout=TIMEOUT + 10) as client:
            items = await _fetch_page(client, api_key, username, limit)
        return [_item_to_video(i) for i in items[:limit]]

    matched: list[dict] = []
    seen_ids: set[str] = set()
    fetch_size = _PAGE_SIZE

    async with httpx.AsyncClient(timeout=TIMEOUT + 10) as client:
        while fetch_size <= _MAX_CRAWL:
            items = await _fetch_page(client, api_key, username, fetch_size)

            if not items:
                break

            videos = [_item_to_video(i) for i in items]

            # Deduplicate because larger fetch_size will include earlier results again
            new_videos = []
            for v in videos:
                vid = v.get("id") or v.get("url")
                if not vid or vid in seen_ids:
                    continue
                seen_ids.add(vid)
                new_videos.append(v)

            if not new_videos and fetch_size > _PAGE_SIZE:
                # No new data found when going deeper
                break

            reached_older_than_from = False

            for v in videos:
                pub_dt = _parse_dt(v.get("published"))

                if not pub_dt:
                    continue

                # If we already reached content older than from_dt,
                # we can stop after this batch
                if from_dt and pub_dt < from_dt:
                    reached_older_than_from = True
                    continue

                if to_dt and pub_dt > to_dt:
                    continue

                if from_dt and pub_dt < from_dt:
                    continue

                vid = v.get("id") or v.get("url")
                if vid and not any((m.get("id") or m.get("url")) == vid for m in matched):
                    matched.append(v)

            if reached_older_than_from:
                break

            # If actor returned fewer than requested, profile is exhausted
            if len(items) < fetch_size:
                break

            fetch_size += _PAGE_SIZE

    # Sort safely by published descending
    matched.sort(
        key=lambda x: _parse_dt(x.get("published")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    return matched[:limit]
    

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
            raise ValueError(f"Apify returned status {resp.status_code}: {resp.text[:300]}")
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
                raise ValueError(f"Failed to fetch comments dataset: status {cresp.status_code}")
            raw_comments = cresp.json()
        else:
            raw_comments = items[0].get("latestComments") or items[0].get("comments") or []
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
            raise ValueError(f"Apify returned status {resp.status_code}: {resp.text[:300]}")
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
                raise ValueError(f"Failed to fetch replies dataset: status {rresp.status_code}")
            raw_replies = rresp.json()
        else:
            raw_replies = items[0].get("replies") or items[0].get("latestComments") or []
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
