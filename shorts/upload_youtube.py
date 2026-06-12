#!/usr/bin/env python3
"""Upload a Short to the Portal Ops channel via the YouTube Data API.

Uses a long-lived OAuth refresh token (see get_youtube_token.py for the
one-time mint). Resumable upload via plain requests — no Google SDK needed.
"""
import os
from pathlib import Path

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = ("https://www.googleapis.com/upload/youtube/v3/videos"
              "?uploadType=resumable&part=snippet,status")


def _access_token() -> str:
    resp = requests.post(TOKEN_URL, data={
        "client_id": os.environ["YT_CLIENT_ID"],
        "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def upload(mp4: Path, title: str, description: str, tags: list[str],
           privacy: str = "public") -> str:
    """Upload the file; return the YouTube video ID."""
    token = _access_token()
    size = mp4.stat().st_size
    meta = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags[:15],
            "categoryId": "27",  # Education
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    init = requests.post(UPLOAD_URL, json=meta, headers={
        "Authorization": f"Bearer {token}",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(size),
    }, timeout=30)
    init.raise_for_status()
    session_uri = init.headers["Location"]

    with open(mp4, "rb") as f:
        put = requests.put(session_uri, data=f, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "video/mp4",
            "Content-Length": str(size),
        }, timeout=600)
    put.raise_for_status()
    video_id = put.json()["id"]
    print(f"uploaded {mp4.name} -> https://youtube.com/shorts/{video_id} ({privacy})")
    return video_id
