import os
import json
import requests
from anthropic import Anthropic
from datetime import datetime, timezone

client = Anthropic()
NEWSAPI_KEY = os.environ["NEWSAPI_KEY"]

# ── CONFIG ──────────────────────────────────────────────────────────────────

QUERIES = [
    "Youngstown State University",
    "YSU Penguins",
    "YSU research",
    "Youngstown State academics",
    "Youngstown State athletics",
]

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

DO NOT PUBLISH if the article:
- Covers protests, activism, demonstrations, or campus unrest
- Covers DEI programs, diversity initiatives, or equity reports
- Covers BLM, Pride, or any social justice campaigns
- Is politically charged in any direction
- Covers budget cuts, layoffs, enrollment declines, or negative institutional news
- Is negative, critical, or embarrassing to YSU
- Is not primarily about YSU (only mentions YSU in passing)
- Is a duplicate or near-duplicate of another article

For each article respond with a JSON array. Each item must have:
- "publish": true or false
- "title": cleaned-up headline (max 12 words, punchy, no clickbait)
- "excerpt": 1-2 sentence summary, positive and factual (max 40 words)
- "tag": single best tag from the provided list
- "date": publication date as YYYY-MM-DD
- "url": original article URL

Return ONLY valid JSON. No markdown, no explanation, no preamble."""


# ── FETCH NEWS ───────────────────────────────────────────────────────────────

def fetch_articles():
    articles = []
    seen_titles = set()
    for query in QUERIES:
        try:
            r = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 10,
                    "apiKey": NEWSAPI_KEY,
                },
                timeout=15,
            )
            data = r.json()
            for a in data.get("articles", []):
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
            print(f"NewsAPI error for '{query}': {e}")
    print(f"Fetched {len(articles)} raw articles")
    return articles


# ── FILTER WITH CLAUDE ────────────────────────────────────────────────────────

def filter_articles(articles, tags):
    if not articles:
        return []
    batch = json.dumps(articles, ensure_ascii=False)
    tag_list = ", ".join(tags)
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
        # strip any accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        filtered = json.loads(raw)
        published = [a for a in filtered if a.get("publish")]
        print(f"Claude approved {len(published)}/{len(articles)} articles")
        return published
    except Exception as e:
        print(f"Claude filter error: {e}")
        return []


# ── BUILD HTML SNIPPETS ───────────────────────────────────────────────────────

def format_date(d):
    try:
        dt = datetime.strptime(d, "%Y-%m-%d")
        return dt.strftime("%b %-d, %Y")
    except Exception:
        return d


def build_news_cards(articles, max_cards=6):
    """2-column story card grid for news/index pages."""
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
    """Numbered list style for section pages."""
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
    """Compact sidebar items."""
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
    """Replace content between <!-- BEGIN:marker_id --> and <!-- END:marker_id -->"""
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

    now_str = build_timestamp()

    # ── INDEX PAGE ──
    print("\n[index.html]")
    idx_articles = filter_articles(all_articles, SECTIONS["index"]["tags"])
    if idx_articles:
        inject("index.html", "LIVE_NEWS",    build_news_cards(idx_articles, 4))
        inject("index.html", "LIVE_SIDEBAR", build_sidebar_items(idx_articles, 4))
        inject("index.html", "LAST_UPDATED", f'<div class="last-updated">{now_str}</div>')

    # ── NEWS PAGE ──
    print("\n[news.html]")
    news_articles = filter_articles(all_articles, SECTIONS["news"]["tags"])
    if news_articles:
        inject("news.html", "LIVE_NEWS",    build_list_items(news_articles, 8))
        inject("news.html", "LIVE_SIDEBAR", build_sidebar_items(news_articles, 4))
        inject("news.html", "LAST_UPDATED", f'<div class="last-updated">{now_str}</div>')

    # ── SPORTS PAGE ──
    print("\n[sports.html]")
    sports_articles = filter_articles(all_articles, SECTIONS["sports"]["tags"])
    if sports_articles:
        inject("sports.html", "LIVE_NEWS",    build_list_items(sports_articles, 6))
        inject("sports.html", "LIVE_SIDEBAR", build_sidebar_items(sports_articles, 4))
        inject("sports.html", "LAST_UPDATED", f'<div class="last-updated">{now_str}</div>')

    # ── SCIENCE PAGE ──
    print("\n[science.html]")
    sci_articles = filter_articles(all_articles, SECTIONS["science"]["tags"])
    if sci_articles:
        inject("science.html", "LIVE_NEWS",    build_list_items(sci_articles, 6))
        inject("science.html", "LIVE_SIDEBAR", build_sidebar_items(sci_articles, 4))
        inject("science.html", "LAST_UPDATED", f'<div class="last-updated">{now_str}</div>')

    # ── STUDENTS PAGE ──
    print("\n[students.html]")
    stu_articles = filter_articles(all_articles, SECTIONS["students"]["tags"])
    if stu_articles:
        inject("students.html", "LIVE_NEWS",    build_list_items(stu_articles, 6))
        inject("students.html", "LIVE_SIDEBAR", build_sidebar_items(stu_articles, 4))
        inject("students.html", "LAST_UPDATED", f'<div class="last-updated">{now_str}</div>')

    # ── FACULTY PAGE ──
    print("\n[faculty.html]")
    fac_articles = filter_articles(all_articles, SECTIONS["faculty"]["tags"])
    if fac_articles:
        inject("faculty.html", "LIVE_NEWS",    build_list_items(fac_articles, 6))
        inject("faculty.html", "LIVE_SIDEBAR", build_sidebar_items(fac_articles, 4))
        inject("faculty.html", "LAST_UPDATED", f'<div class="last-updated">{now_str}</div>')

    # ── ALUMNI PAGE ──
    print("\n[alumni.html]")
    alum_articles = filter_articles(all_articles, SECTIONS["alumni"]["tags"])
    if alum_articles:
        inject("alumni.html", "LIVE_NEWS",    build_list_items(alum_articles, 6))
        inject("alumni.html", "LIVE_SIDEBAR", build_sidebar_items(alum_articles, 4))
        inject("alumni.html", "LAST_UPDATED", f'<div class="last-updated">{now_str}</div>')

    print("\n=== Pipeline complete ===")


if __name__ == "__main__":
    main()
