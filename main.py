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


class VideoRequest(BaseModel):
    username: str
    api_key: str
    date_from: str | None = None
    date_to: str | None = None
    limit: int = 30


class CommentRequest(BaseModel):
    video_url: str
    api_key: str
    count: int = 50


async def _scrape_videos(req: VideoRequest):
    api_key = req.api_key.strip()
    if not api_key:
        return {"videos": [], "total": 0, "username": req.username, "error": "API key is required"}

    key = cache.make_key("videos", api_key, req.username, req.limit, req.date_from, req.date_to)
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        videos = await scraper.scrape_videos(
            api_key=api_key,
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
    api_key = req.api_key.strip()
    if not api_key:
        return {"comments": [], "total": 0, "error": "API key is required"}

    key = cache.make_key("comments", api_key, req.video_url, req.count)
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        comments = await scraper.scrape_comments(
            api_key=api_key,
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
    print("TikSpy is running in per-request API key mode.")
    port = int(os.getenv("PORT", "5000"))
    print(f"TikSpy running on http://0.0.0.0:{port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
