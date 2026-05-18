"""Post a message (with optional image) to your personal LinkedIn feed.

Library:
    post_to_linkedin(text, access_token, person_urn, image_bytes=None) -> post URN string

CLI:
    python linkedin_post.py "Your text here" [path/to/image.png]
"""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"
REGISTER_UPLOAD_URL = "https://api.linkedin.com/v2/assets?action=registerUpload"
TOKEN_FILE = Path(__file__).parent / "token.json"


def _upload_image(image_bytes: bytes, access_token: str, person_urn: str) -> str:
    register_body = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": person_urn,
            "serviceRelationships": [
                {
                    "relationshipType": "OWNER",
                    "identifier": "urn:li:userGeneratedContent",
                }
            ],
        }
    }
    resp = requests.post(
        REGISTER_UPLOAD_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=register_body,
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"registerUpload failed ({resp.status_code}): {resp.text}")
    data = resp.json()["value"]
    upload_url = data["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
    asset_urn = data["asset"]

    put_resp = requests.put(
        upload_url,
        headers={"Authorization": f"Bearer {access_token}"},
        data=image_bytes,
        timeout=120,
    )
    if not put_resp.ok:
        raise RuntimeError(f"image PUT failed ({put_resp.status_code}): {put_resp.text}")
    return asset_urn


def post_to_linkedin(
    text: str,
    access_token: str,
    person_urn: str,
    image_bytes: bytes | None = None,
) -> str:
    share_content: dict = {
        "shareCommentary": {"text": text},
        "shareMediaCategory": "NONE",
    }
    if image_bytes:
        asset_urn = _upload_image(image_bytes, access_token, person_urn)
        share_content["shareMediaCategory"] = "IMAGE"
        share_content["media"] = [{"status": "READY", "media": asset_urn}]

    body = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {"com.linkedin.ugc.ShareContent": share_content},
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    resp = requests.post(
        UGC_POSTS_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"LinkedIn post failed ({resp.status_code}): {resp.text}")
    return resp.headers.get("x-restli-id") or resp.json().get("id", "")


def load_credentials() -> tuple[str, str]:
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    urn = os.environ.get("LINKEDIN_PERSON_URN")
    if token and urn:
        return token, urn
    if not TOKEN_FILE.exists():
        raise RuntimeError(
            f"No credentials. Set LINKEDIN_ACCESS_TOKEN and LINKEDIN_PERSON_URN "
            f"env vars, or run linkedin_auth.py to create {TOKEN_FILE}."
        )
    data = json.loads(TOKEN_FILE.read_text())
    return data["access_token"], data["person_urn"]


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: python linkedin_post.py "Your post text" [path/to/image]', file=sys.stderr)
        return 1
    text = sys.argv[1]
    image_bytes = None
    if len(sys.argv) > 2:
        image_bytes = Path(sys.argv[2]).read_bytes()
    access_token, person_urn = load_credentials()
    post_id = post_to_linkedin(text, access_token, person_urn, image_bytes=image_bytes)
    print(f"Posted: {post_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
