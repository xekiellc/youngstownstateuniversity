import os
import json
import requests
import re
from anthropic import Anthropic
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

client = Anthropic(timeout=60.0)
NEWSAPI_KEY = os.environ["NEWSAPI_KEY"]

# ── CONFIG ──────────────────────────────────────────────────────────────────

NEWSAPI_QUERIES = [
    "Youngstown State University",
    "YSU Penguins",
    "Youngstown State athletics",
]

YSU_NEWS_URL = "https://ysu.edu/news"
YSU_BASE_URL = "https://ysu.edu"

SECTIONS = {
    "index":    {"label": "News",      "tags": ["News","Academics","Research","Sports","Students","Faculty","Alumni","Campus"]},
    "news":     {"label": "News",      "tags": ["News","Academics","Campus","Awards","Community","Research"]},
    "sports":   {"label": "Sports",    "tags": ["Sports","Athletics","Baseball","Football","Basketball","Softball","Track"]},
    "science":  {"label": "Science",   "tags": ["Research","Biology","Engineering","Chemistry","Physics","Health Sciences","Computer Science","Environmental"]},
    "students": {"label": "Students",  "tags": ["Students","Achievement","Scholarships","Research","Campus Life","Veterans","Leadership"]},
    "faculty":  {"label": "Faculty",   "tags": ["Faculty","Engineering","Sciences","Health","Business","Arts","Liberal Arts","Education"]},
    "alumni":   {"label": "Alumni",    "tags": ["Alumni","Business","Medicine","Law","Sports","Science","Arts","Public Service"]},
}

FILTER_PROMPT = """You are the content editor for youngstownstateuniversity.com — a pro-YSU fan site.

Your job is to review news articles about Youngstown State University and decide which ones to publish.

PUBLISH if the article is:
- Positive coverage of YSU academics, research, achievements, athletics, student success, faculty honors, or alumni accomplishments
- Neutral factual reporting about YSU programs, events, rankings, or announcements
- Coverage of Penguins athletics results, scores, standings, or player achievements
- Any factual news that is primarily about YSU or its students, faculty, or alumni

DO NOT PUBLISH if the article:
- Covers protests, activism, demonstrations, or campus unrest
- Covers DEI programs, diversity initiatives, or equity reports
- Covers BLM, Pride, or any social justice campaigns
- Is politically charged in any direction
- Covers budget cuts, layoffs, enrollment declines, or negative institutional news
- Is negative, critical, or embarrassing to YSU
- Is not primarily about YSU (only mentions YSU in passing)
- Is a duplicate or near-duplicate of another article

When in doubt, PUBLISH. A neutral story is better than no story.

For each article respond with a JSON array. Each item must have:
- "publish": true or false
- "title": cleaned-up headline (max 12 words, punchy, no clickbait)
- "excerpt": 1-2 sentence summary, positive and factual (max 40 words)
- "tag": single best tag from the provided list
- "date": publication date as YYYY-MM-DD
- "url": original article URL

Return ONLY valid JSON. No markdown, no explanation, no preamble."""


# ── SCRAPE YSU NEWS PAGE ──────────────────────────────────────────────────────

def scrape_ysu_news():
    articles = []
    try:
        r = requests.get(YSU_NEWS_URL, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        html = r.text
        # Find all news article links — pattern: /news/some-slug
        # Also find h5 links with titles
        pattern = r'<a[^>]+href="(/news/[^"]+)"[^>]*>([^<]+)</a>'
        matches = re.findall(pattern, html)
        seen = set()
        today = datetime.now(timezone.utc)
        for path, title in matches:
            title = title.strip()
            if not title or len(title) < 10:
                continue
            if path in seen:
                continue
            seen.add(path)
            url = YSU_BASE_URL + path
            articles.append({
                "title":   title,
                "excerpt": "",
                "url":     url,
                "date":    today.strftime("%Y-%m-%d"),
                "source":  "ysu.edu",
            })
        # Also look for date-stamped items
        # Pattern: Mon, 08/03/2026 type dates near titles
        date_pattern = r'(\w{3}, \d{2}/\d{2}/\d{4})'
        dates = re.findall(date_pattern, html)

        print(f"  YSU scrape: {len(articles)} articles found")
    except Exception as e:
        print(f"  YSU scrape error: {e}")
    return articles[:20]  # cap at 20


# ── FETCH FROM NEWSAPI ────────────────────────────────────────────────────────

def fetch_newsapi():
    articles = []
    seen_titles = set()
    from_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for query in NEWSAPI_QUERIES:
        try:
            r = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "from": from_date,
                    "pageSize": 10,
                    "apiKey": NEWSAPI_KEY,
                },
                timeout=15,
            )
            data = r.json()
            raw = data.get("articles", [])
            print(f"  NewsAPI '{query}': {len(raw)} results")
            for a in raw:
                title = (a.get("title") or "").strip()
                if not title or title in seen_titles:
                    continue
                if "[Removed]" in title:
                    continue
                seen_titles.add(title)
                articles.append({
                    "title":   title,
                    "excerpt": (a.get("description") or "")[:300],
                    "url":     a.get("url", ""),
                    "date":    (a.get("publishedAt") or "")[:10],
                    "source":  (a.get("source") or {}).get("name", ""),
                })
        except Exception as e:
            print(f"  NewsAPI error '{query}': {e}")
    return articles


# ── FETCH ALL ─────────────────────────────────────────────────────────────────

def fetch_articles():
    articles = []
    seen_titles = set()

    print("Scraping YSU news page...")
    for a in scrape_ysu_news():
        if a["title"] not in seen_titles:
            seen_titles.add(a["title"])
            articles.append(a)

    print("Fetching from NewsAPI...")
    for a in fetch_newsapi():
        if a["title"] not in seen_titles:
            seen_titles.add(a["title"])
            articles.append(a)

    print(f"Fetched {len(articles)} unique raw articles total")
    for i, a in enumerate(articles, 1):
        print(f"  {i}. [{a.get('date','')}] {a.get('title','')[:80]}")
    return articles


# ── FILTER WITH CLAUDE ────────────────────────────────────────────────────────

def filter_all_articles(articles):
    if not articles:
        return []
    all_tags = ["News","Academics","Research","Sports","Athletics","Students","Faculty","Alumni",
                "Campus","Awards","Community","Baseball","Football","Basketball","Softball","Track",
                "Biology","Engineering","Chemistry","Physics","Health Sciences","Computer Science",
                "Environmental","Achievement","Scholarships","Campus Life","Veterans","Leadership",
                "Business","Arts","Liberal Arts","Education","Medicine","Law","Public Service"]
    batch = json.dumps(articles, ensure_ascii=False)
    tag_list = ", ".join(all_tags)
    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": f"{FILTER_PROMPT}\n\nAvailable tags: {tag_list}\n\nArticles to review:\n{batch}"
            }]
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        filtered = json.loads(raw)
        for a in filtered:
            status = "PUBLISH" if a.get("publish") else "REJECT"
            print(f"  {status}: {a.get('title','')[:80]}")
        published = [a for a in filtered if a.get("publish")]
        print(f"Claude approved {len(published)}/{len(articles)} articles")
        return published
    except Exception as e:
        print(f"Claude filter error: {e}")
        return []


def filter_by_tags(articles, tags):
    tag_set = set(t.lower() for t in tags)
    matched = [a for a in articles if a.get("tag", "").lower() in tag_set]
    if not matched:
        matched = articles[:4]
    return matched


# ── BUILD HTML SNIPPETS ───────────────────────────────────────────────────────

def format_date(d):
    try:
        dt = datetime.strptime(d, "%Y-%m-%d")
        return dt.strftime("%b %-d, %Y")
    except Exception:
        return d


def build_news_cards(articles, max_cards=6):
    if not articles:
        return '<p style="color:#aaa;font-size:13px;padding:20px 0;">No new stories at this time. Check back soon.</p>'
    html = '<div class="news-grid">'
    for a in articles[:max_cards]:
        url   = a.get("url", "#")
        tag   = a.get("tag", "News")
        title = a.get("title", "")
        exc   = a.get("excerpt", "")
        date  = format_date(a.get("date", ""))
        html += f"""
  <div class="story-card">
    <div class="story-tag">{tag}</div>
    <h3 class="story-title"><a href="{url}" target="_blank" rel="noopener">{title}</a></h3>
    <p class="story-excerpt">{exc}</p>
    <div class="story-byline">{date}</div>
  </div>"""
    html += "\n</div>"
    return html


def build_list_items(articles, max_items=8):
    if not articles:
        return '<p style="color:#aaa;font-size:13px;padding:20px 0;">No new stories at this time. Check back soon.</p>'
    html = '<div class="news-list">'
    for i, a in enumerate(articles[:max_items], 1):
        url   = a.get("url", "#")
        tag   = a.get("tag", "News")
        title = a.get("title", "")
        exc   = a.get("excerpt", "")
        date  = format_date(a.get("date", ""))
        html += f"""
  <div class="news-item">
    <div class="ni-date-block">
      <div class="ni-month">{date[:3].upper() if date else 'NOW'}</div>
      <div class="ni-day">{date[4:6].lstrip('0') if len(date) > 5 else str(i)}</div>
      <div class="ni-year">{date[-4:] if len(date) >= 4 else '2026'}</div>
    </div>
    <div>
      <div class="ni-tag">{tag}</div>
      <div class="ni-title"><a href="{url}" target="_blank" rel="noopener">{title}</a></div>
      <p class="ni-excerpt">{exc}</p>
    </div>
  </div>"""
    html += "\n</div>"
    return html


def build_sidebar_items(articles, max_items=4):
    if not articles:
        return ""
    html = ""
    for a in articles[:max_items]:
        url   = a.get("url", "#")
        tag   = a.get("tag", "News")
        title = a.get("title", "")
        date  = format_date(a.get("date", ""))
        html += f"""
  <div class="sidebar-item">
    <div class="si-tag">{tag}</div>
    <div class="si-title"><a href="{url}" target="_blank" rel="noopener">{title}</a></div>
    <div class="si-meta">{date}</div>
  </div>"""
    return html


# ── INJECT INTO HTML ──────────────────────────────────────────────────────────

def inject(filepath, marker_id, new_html):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        start_tag = f"<!-- BEGIN:{marker_id} -->"
        end_tag   = f"<!-- END:{marker_id} -->"
        if start_tag not in content:
            print(f"  Marker '{marker_id}' not found in {filepath} — skipping")
            return
        before = content.split(start_tag)[0]
        after  = content.split(end_tag)[1]
        content = before + start_tag + "\n" + new_html + "\n" + end_tag + after
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  Injected '{marker_id}' into {filepath}")
    except Exception as e:
        print(f"  Inject error ({filepath} / {marker_id}): {e}")


# ── TIMESTAMP ─────────────────────────────────────────────────────────────────

def build_timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("Last updated: %B %-d, %Y at %-I:%M %p UTC")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("=== YSU News Pipeline starting ===")
    all_articles = fetch_articles()
    if not all_articles:
        print("No articles fetched — exiting.")
        return

    print("\nFiltering all articles with Claude...")
    approved = filter_all_articles(all_articles)
    if not approved:
        print("No articles approved — exiting.")
        return

    now_str = build_timestamp()

    pages = [
        ("index.html",    SECTIONS["index"]["tags"],    True),
        ("news.html",     SECTIONS["news"]["tags"],     False),
        ("sports.html",   SECTIONS["sports"]["tags"],   False),
        ("science.html",  SECTIONS["science"]["tags"],  False),
        ("students.html", SECTIONS["students"]["tags"], False),
        ("faculty.html",  SECTIONS["faculty"]["tags"],  False),
        ("alumni.html",   SECTIONS["alumni"]["tags"],   False),
    ]

    for filename, tags, use_cards in pages:
        print(f"\n[{filename}]")
        page_articles = filter_by_tags(approved, tags)
        if not page_articles:
            print(f"  No matching articles for {filename}")
            continue
        if use_cards:
            news_html = build_news_cards(page_articles, 4)
        else:
            news_html = build_list_items(page_articles, 6)
        inject(filename, "LIVE_NEWS",    news_html)
        inject(filename, "LIVE_SIDEBAR", build_sidebar_items(page_articles, 4))
        inject(filename, "LAST_UPDATED", f'<div class="last-updated">{now_str}</div>')

    print("\n=== Pipeline complete ===")


if __name__ == "__main__":
    main()
