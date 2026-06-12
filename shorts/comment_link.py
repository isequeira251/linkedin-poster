#!/usr/bin/env python3
"""Post the Short link as the first comment on today's LinkedIn post.

Link-in-first-comment preserves post reach vs. an external link card.
Uses the same token/scope (w_member_social) as linkedin_post.py.
"""
import os
import urllib.parse

import requests

API = "https://api.linkedin.com/v2"


def post_comment(post_urn: str, text: str) -> str:
    token = os.environ["LINKEDIN_ACCESS_TOKEN"]
    actor = os.environ["LINKEDIN_PERSON_URN"]
    url = f"{API}/socialActions/{urllib.parse.quote(post_urn, safe='')}/comments"
    resp = requests.post(url, json={
        "actor": actor,
        "message": {"text": text},
    }, headers={
        "Authorization": f"Bearer {token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }, timeout=30)
    resp.raise_for_status()
    comment_urn = resp.headers.get("x-restli-id") or resp.json().get("$URN", "")
    print(f"first comment posted on {post_urn}: {comment_urn}")
    return comment_urn
