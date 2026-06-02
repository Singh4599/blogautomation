#!/usr/bin/env python3
"""
365 Spicery — AI Blog Automation
Generates SEO-optimized blog posts using Gemini AI and publishes to Shopify.

Usage:
  python blog_automation.py           # Auto-picks today's topic
  python blog_automation.py --dry-run # Generate post but don't publish (preview mode)
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, timezone

# ─── Configuration ────────────────────────────────────────────────────────────
SHOPIFY_STORE   = os.environ.get("SHOPIFY_STORE", "2f284e-5e.myshopify.com")
SHOPIFY_TOKEN   = os.environ.get("SHOPIFY_ACCESS_TOKEN")
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY")
API_VERSION     = "2024-01"
BLOG_HANDLE     = "news"
DRY_RUN         = "--dry-run" in sys.argv

# ─── Validate Secrets ─────────────────────────────────────────────────────────
if not SHOPIFY_TOKEN:
    print("❌ Missing SHOPIFY_ACCESS_TOKEN environment variable.")
    sys.exit(1)
if not GEMINI_API_KEY:
    print("❌ Missing GEMINI_API_KEY environment variable.")
    sys.exit(1)

# ─── Shopify Headers ──────────────────────────────────────────────────────────
SHOPIFY_HEADERS = {
    "X-Shopify-Access-Token": SHOPIFY_TOKEN,
    "Content-Type": "application/json"
}
BASE = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}"

# ─── Gemini API (Direct HTTP — no SDK needed) ────────────────────────────────
GEMINI_MODEL    = "gemini-1.5-flash"
GEMINI_URL      = f"https://generativelanguage.googleapis.com/v1/models/{GEMINI_MODEL}:generateContent"


def call_gemini(prompt, temperature=0.75, max_tokens=2048):
    """Call Gemini REST API directly — works with any free tier key."""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens
        }
    }
    res = requests.post(
        GEMINI_URL,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=60
    )
    res.raise_for_status()
    data = res.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


# ─────────────────────────────────────────────────────────────────────────────
# TOPIC SELECTION
# ─────────────────────────────────────────────────────────────────────────────

def load_topics():
    topics_file = os.path.join(os.path.dirname(__file__), "blog_topics.json")
    with open(topics_file, "r", encoding="utf-8") as f:
        return json.load(f)

def get_todays_topic(topics):
    now = datetime.now(timezone.utc)
    day_of_year = now.timetuple().tm_yday
    year_offset  = (now.year - 2025) * 365
    index = (day_of_year + year_offset) % len(topics)
    return topics[index]


# ─────────────────────────────────────────────────────────────────────────────
# AI CONTENT GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def generate_blog_body(topic):
    prompt = f"""You are an expert content writer for 365 Spicery, a premium Indian spice manufacturer and B2B exporter based in India. The company specialises in blended spices, seasonings, chilli powder, turmeric, cumin, chutney powders, dip mixes, dehydrated spices, Jain spices, spice pastes, and private-label manufacturing.

Write a professional, SEO-optimised blog post on the following topic:

Title: {topic['title']}
Target Keyword: {topic['keyword']}
Primary Audience: {topic['audience']}
Tone: Informative, authoritative, and slightly conversational

STRICT REQUIREMENTS:
1. Word count: 900–1200 words
2. Format: Clean HTML using only <h2>, <h3>, <p>, <ul>, <li>, <strong>, <em> tags
3. Include the target keyword naturally 4–6 times throughout the post
4. Structure:
   - Opening paragraph (no heading) — hook the reader immediately
   - 3–4 <h2> sections with substantial, useful content
   - Optional <h3> sub-sections where relevant
   - A closing paragraph with a natural call-to-action mentioning 365 Spicery
5. Mention "365 Spicery" naturally 3–4 times — do NOT over-promote
6. Make the content genuinely educational and useful — not keyword filler
7. Do NOT include: <html>, <head>, <body>, <title>, or any meta tags
8. Do NOT use markdown — return ONLY raw HTML starting from the first <p> tag
9. No code blocks or triple backticks in your response

Write the blog post now:"""

    print("   → Calling Gemini AI (this may take 15–30 seconds)...")
    return call_gemini(prompt, temperature=0.75, max_tokens=2048)


def generate_seo_meta(topic):
    prompt = f"""Generate SEO metadata for a blog post about "{topic['title']}" targeting the keyword "{topic['keyword']}".

Return ONLY a valid JSON object with these two keys (no markdown, no code blocks):
{{
  "seo_title": "...",
  "meta_description": "..."
}}

Rules:
- seo_title: max 60 characters, include keyword, brand name "365 Spicery" if it fits
- meta_description: max 155 characters, compelling, include keyword naturally"""

    raw = call_gemini(prompt, temperature=0.3, max_tokens=200)

    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "seo_title": topic["title"][:60],
            "meta_description": f"Discover expert insights on {topic['keyword']}. 365 Spicery — India's trusted spice manufacturer."[:155]
        }


# ─────────────────────────────────────────────────────────────────────────────
# SHOPIFY PUBLISHING
# ─────────────────────────────────────────────────────────────────────────────

def get_blog_id(handle=BLOG_HANDLE):
    res = requests.get(f"{BASE}/blogs.json", headers=SHOPIFY_HEADERS, timeout=15)
    res.raise_for_status()
    blogs = res.json().get("blogs", [])
    for blog in blogs:
        if blog["handle"] == handle:
            return blog["id"]
    if blogs:
        print(f"   ⚠️  Blog '{handle}' not found. Using: {blogs[0]['handle']}")
        return blogs[0]["id"]
    raise ValueError("No blogs found on this Shopify store.")


def publish_article(blog_id, topic, body_html, seo):
    tags = ", ".join(topic.get("tags", [topic["category"]]))
    payload = {
        "article": {
            "title":      topic["title"],
            "author":     "365 Spicery",
            "tags":       tags,
            "body_html":  body_html,
            "published":  True,
            "metafields": [
                {
                    "key":       "title_tag",
                    "value":     seo["seo_title"][:60],
                    "type":      "single_line_text_field",
                    "namespace": "global"
                },
                {
                    "key":       "description_tag",
                    "value":     seo["meta_description"][:155],
                    "type":      "single_line_text_field",
                    "namespace": "global"
                }
            ]
        }
    }
    res = requests.post(
        f"{BASE}/blogs/{blog_id}/articles.json",
        headers=SHOPIFY_HEADERS,
        json=payload,
        timeout=20
    )
    return res.status_code, res.json()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    start_time = time.time()
    print("=" * 60)
    print("🌶️   365 Spicery — AI Blog Automation")
    print(f"📅  Date: {datetime.now().strftime('%A, %d %B %Y')}")
    if DRY_RUN:
        print("🔍  DRY RUN MODE — post will NOT be published")
    print("=" * 60)

    topics = load_topics()
    topic  = get_todays_topic(topics)
    print(f"\n📝 Today's Topic  : {topic['title']}")
    print(f"🔑 Target Keyword : {topic['keyword']}")
    print(f"🏷️  Category       : {topic['category']}")

    print("\n🤖 Generating blog content with Gemini AI...")
    body_html = generate_blog_body(topic)
    print(f"✅ Content generated!")

    print("\n🔍 Generating SEO metadata...")
    seo = generate_seo_meta(topic)
    print(f"   SEO Title  : {seo['seo_title']}")
    print(f"   Meta Desc  : {seo['meta_description']}")

    if DRY_RUN:
        print("\n" + "─" * 60)
        print("📄 PREVIEW (first 500 chars):")
        print(body_html[:500] + "...")
        print("\n✅ Dry run complete. No post was published.")
        return

    print("\n📚 Fetching Shopify blog ID...")
    blog_id = get_blog_id()
    print(f"   Blog ID: {blog_id}")

    print("\n🚀 Publishing to Shopify...")
    status, resp = publish_article(blog_id, topic, body_html, seo)

    elapsed = round(time.time() - start_time, 1)

    if status == 201:
        article = resp.get("article", {})
        print(f"\n✅ Published successfully in {elapsed}s!")
        print(f"   Article ID : {article.get('id')}")
        print(f"   URL        : https://{SHOPIFY_STORE}/blogs/{BLOG_HANDLE}/{article.get('handle')}")
    else:
        print(f"\n❌ Publish failed — HTTP {status}")
        print(f"   Response   : {json.dumps(resp, indent=2)}")
        sys.exit(1)

    print("=" * 60)


if __name__ == "__main__":
    main()
