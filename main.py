import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from cache import TTLCache
import scraper

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

cache = TTLCache(ttl=600, max_size=30)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.middleware("http")
async def no_cache_headers(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Settings ─────────────────────────────────────────────────────

class ApiKeyRequest(BaseModel):
    api_key: str


@app.get("/settings/status")
async def settings_status():
    token = scraper.APIFY_TOKEN
    if token:
        masked = token[:4] + "•" * (len(token) - 8) + token[-4:]
    else:
        masked = ""
    return {"configured": bool(token), "masked": masked}


@app.post("/settings/api-key")
async def update_api_key(req: ApiKeyRequest):
    key = req.api_key.strip()
    if not key:
        return {"success": False, "error": "API key cannot be empty"}
    scraper.APIFY_TOKEN = key
    # Clear cache so next fetch uses the new key
    cache._store.clear()
    return {"success": True}


# ── Scrape endpoints ──────────────────────────────────────────────

class VideoRequest(BaseModel):
    username: str
    date_from: str | None = None
    date_to: str | None = None
    limit: int = 30


class CommentRequest(BaseModel):
    video_url: str
    count: int = 50


async def _scrape_videos(req: VideoRequest):
    key = cache.make_key("videos", req.username, req.limit, req.date_from, req.date_to)
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        videos = await scraper.scrape_videos(
            username=req.username,
            date_from=req.date_from,
            date_to=req.date_to,
            limit=req.limit,
        )
        result = {"videos": videos, "total": len(videos), "username": req.username}
        cache.set(key, result)
        return result
    except Exception as e:
        return {"videos": [], "total": 0, "username": req.username, "error": str(e)}


async def _scrape_comments(req: CommentRequest):
    key = cache.make_key("comments", req.video_url, req.count)
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        comments = await scraper.scrape_comments(
            video_url=req.video_url,
            count=req.count,
        )
        result = {"comments": comments, "total": len(comments)}
        cache.set(key, result)
        return result
    except Exception as e:
        return {"comments": [], "total": 0, "error": str(e)}


@app.post("/scrape/videos")
async def scrape_videos(req: VideoRequest):
    return await _scrape_videos(req)


@app.post("/scrape/comments")
async def scrape_comments(req: CommentRequest):
    return await _scrape_comments(req)


# Legacy aliases so old cached frontends keep working
@app.post("/api/scrape/videos")
async def scrape_videos_legacy(req: VideoRequest):
    return await _scrape_videos(req)


@app.post("/api/scrape/comments")
async def scrape_comments_legacy(req: CommentRequest):
    return await _scrape_comments(req)


if __name__ == "__main__":
    token = scraper.APIFY_TOKEN
    if not token:
        print("WARNING: APIFY_API_TOKEN is not set. Scraping will not work.")
    else:
        print("APIFY_API_TOKEN is configured.")

    port = int(os.getenv("PORT", "5000"))
    print(f"TikSpy running on http://0.0.0.0:{port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
