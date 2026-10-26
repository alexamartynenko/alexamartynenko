"""Minimal Typefully API v2 client: create an X draft and publish or queue it."""

import os

import httpx

API = "https://api.typefully.com/v2"
SOCIAL_SET_ID = os.environ.get("TYPEFULLY_SOCIAL_SET_ID", "350599")


def create_x_draft(text: str, publish_at: str | None) -> dict:
    """publish_at: "now", "next-free-slot", an ISO 8601 time, or None to keep as draft.

    A thread is written as several posts separated by a line with only ---.
    """
    posts = [{"text": part.strip()} for part in text.split("\n---\n") if part.strip()]
    body = {"platforms": {"x": {"enabled": True, "posts": posts}}}
    if publish_at:
        body["publish_at"] = publish_at
    response = httpx.post(
        f"{API}/social-sets/{SOCIAL_SET_ID}/drafts",
        headers={"Authorization": f"Bearer {os.environ['TYPEFULLY_API_KEY']}"},
        json=body,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
