import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import dateparser
import feedparser
import httpx
from src.llm_engine import extract_with_fallback
from src.resolver import EntityResolver
from src.schemas import JobContent, JobEntity, NewsContent, NewsEntity, SourceInfo

resolver = EntityResolver()
SEEN_CACHE_PATH = "data/seen_signals.json"

NEWS_FEEDS = [
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("MIT Tech Review AI", "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
    ("Wired AI", "https://www.wired.com/feed/tag/ai/latest/rss"),
]

JOB_FEEDS = [
    ("WeWorkRemotely Programming", "https://weworkremotely.com/categories/remote-programming-jobs.rss"),
    ("Remotive AI/Software", "https://remotive.com/remote-jobs/software-dev/feed"),
]


def load_seen_hashes() -> set[str]:
    if os.path.exists(SEEN_CACHE_PATH):
        with open(SEEN_CACHE_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen_hashes(hashes: set[str]):
    with open(SEEN_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(list(hashes), f, indent=2)


def parse_and_check_24h(raw_date: str | None, url: str, seen_hashes: set[str]) -> str | None:
    """Normalizes dates to ISO-8601 and returns timestamp ONLY if within last 24 hours."""
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=24)

    if raw_date:
        dt = dateparser.parse(str(raw_date), settings={"RETURN_AS_TIMEZONE_AWARE": True})
        if dt:
            dt_utc = dt.astimezone(timezone.utc)
            if cutoff <= dt_utc <= now_utc + timedelta(minutes=15):
                return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            return None

    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
    if url_hash not in seen_hashes:
        seen_hashes.add(url_hash)
        return now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


async def fetch_single_news_feed(client: httpx.AsyncClient, source_name: str, feed_url: str, seen_hashes: set[str]) -> list[dict]:
    items = []
    try:
        resp = await client.get(feed_url, timeout=10.0)
        feed = feedparser.parse(resp.text)
        for entry in feed.entries[:25]:
            link = entry.get("link", "").strip()
            pub_raw = entry.get("published") or entry.get("updated")
            iso_date = parse_and_check_24h(pub_raw, link, seen_hashes)
            if not iso_date or not link:
                continue
            title = entry.get("title", "").strip()
            raw_summary = entry.get("summary", title)
            items.append({
                "source_name": source_name,
                "link": link,
                "title": title,
                "raw_summary": raw_summary,
                "iso_date": iso_date,
            })
    except Exception as e:
        print(f"  Warning on {source_name}: {e}")
    return items


async def scrape_news(client: httpx.AsyncClient, seen_hashes: set[str]) -> list[dict]:
    print("Scanning 5 AI News sources concurrently for last-24-hour articles...")
    batches = await asyncio.gather(*(
        fetch_single_news_feed(client, name, url, seen_hashes) for name, url in NEWS_FEEDS
    ))
    raw_articles = [item for batch in batches for item in batch]

    news_items = []
    for idx, art in enumerate(raw_articles):
        # Run LLM extraction on top 3 articles (max_retries=1 so it finishes in seconds)
        if idx < 3:
            try:
                extracted = await extract_with_fallback(
                    f"Title: {art['title']}\nPublished: {art['iso_date']}\nContent: {art['raw_summary']}",
                    NewsContent,
                    max_retries=1,
                )
                summary_clean = extracted.summary or art["title"]
                entities = [resolver.resolve(e, art["link"]) for e in extracted.entities_mentioned]
            except Exception:
                summary_clean = art["title"]
                entities = []
        else:
            summary_clean = art["title"]
            entities = []

        entity = NewsEntity(
            source=SourceInfo(name=art["source_name"], url=art["link"]),
            content=NewsContent(
                title=art["title"],
                summary=summary_clean[:400],
                published_date=art["iso_date"],
                entities_mentioned=entities,
            ),
        )
        news_items.append(entity.model_dump())

    return news_items


async def scrape_jobs(client: httpx.AsyncClient, seen_hashes: set[str]) -> list[dict]:
    print("Scanning 5 AI Job sources concurrently for last-24-hour postings...")
    ai_terms = ("ai", "machine learning", "ml", "llm", "data scientist", "nlp", "computer vision", "deep learning", "python", "engineer")

    async def get_remoteok():
        out = []
        try:
            r = await client.get("https://remoteok.com/api", headers={"User-Agent": "FrontierAtlas/1.0"}, timeout=10.0)
            if r.status_code == 200:
                for item in r.json()[1:60]:
                    title = str(item.get("position", ""))
                    tags = " ".join(item.get("tags", []))
                    if not any(t in (title + " " + tags).lower() for t in ai_terms):
                        continue
                    link = item.get("url", "https://remoteok.com")
                    iso_date = parse_and_check_24h(item.get("date"), link, seen_hashes)
                    if iso_date:
                        company = resolver.resolve(item.get("company", "Unknown"), link)
                        out.append(JobEntity(content=JobContent(company=company, date=iso_date, is_remote=True, role_family="Engineering")).model_dump())
        except Exception as e:
            print(f"  Warning on RemoteOK: {e}")
        return out

    async def get_himalayas():
        out = []
        try:
            r = await client.get("https://himalayas.app/jobs/api?limit=50", timeout=10.0)
            if r.status_code == 200:
                for item in r.json().get("jobs", []):
                    title = str(item.get("title", ""))
                    if not any(t in title.lower() for t in ai_terms):
                        continue
                    link = item.get("applicationLink") or "https://himalayas.app"
                    pub_ts = item.get("pubDate")
                    raw_date = datetime.fromtimestamp(pub_ts, tz=timezone.utc).isoformat() if isinstance(pub_ts, (int, float)) else str(pub_ts)
                    iso_date = parse_and_check_24h(raw_date, link, seen_hashes)
                    if iso_date:
                        company = resolver.resolve(item.get("companyName", "Unknown"), link)
                        out.append(JobEntity(content=JobContent(company=company, date=iso_date, is_remote=True, role_family="Engineering")).model_dump())
        except Exception as e:
            print(f"  Warning on Himalayas: {e}")
        return out

    async def get_jobicy():
        out = []
        try:
            r = await client.get("https://jobicy.com/api/v2/remote-jobs?count=50&tag=ai", timeout=10.0)
            if r.status_code == 200:
                for item in r.json().get("jobs", []):
                    link = item.get("url", "https://jobicy.com")
                    iso_date = parse_and_check_24h(item.get("pubDate"), link, seen_hashes)
                    if iso_date:
                        company = resolver.resolve(item.get("companyName", "Unknown"), link)
                        out.append(JobEntity(content=JobContent(company=company, date=iso_date, is_remote=True, role_family="AI / Engineering")).model_dump())
        except Exception as e:
            print(f"  Warning on Jobicy: {e}")
        return out

    async def get_rss_board(board_name: str, feed_url: str):
        out = []
        try:
            resp = await client.get(feed_url, timeout=10.0)
            feed = feedparser.parse(resp.text)
            for entry in feed.entries[:30]:
                title = entry.get("title", "")
                if not any(t in title.lower() for t in ai_terms):
                    continue
                link = entry.get("link", feed_url)
                iso_date = parse_and_check_24h(entry.get("published"), link, seen_hashes)
                if iso_date:
                    raw_comp = title.split(":")[0] if ":" in title else board_name
                    company = resolver.resolve(raw_comp, link)
                    out.append(JobEntity(content=JobContent(company=company, date=iso_date, is_remote=True, role_family="Engineering")).model_dump())
        except Exception as e:
            print(f"  Warning on {board_name}: {e}")
        return out

    results = await asyncio.gather(
        get_remoteok(),
        get_himalayas(),
        get_jobicy(),
        *(get_rss_board(name, url) for name, url in JOB_FEEDS),
    )
    return [job for batch in results for job in batch]


async def main():
    os.makedirs("data", exist_ok=True)
    seen_hashes = load_seen_hashes()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        news, jobs = await asyncio.gather(
            scrape_news(client, seen_hashes),
            scrape_jobs(client, seen_hashes),
        )

    save_seen_hashes(seen_hashes)

    with open("data/news.json", "w", encoding="utf-8") as f:
        json.dump(news, f, indent=2, ensure_ascii=False)

    with open("data/jobs.json", "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)

    existing_logs = []
    if os.path.exists("data/entity_mapping_log.json"):
        with open("data/entity_mapping_log.json", "r", encoding="utf-8") as f:
            existing_logs = json.load(f)
    existing_logs.extend([log.model_dump() for log in resolver.logs])
    with open("data/entity_mapping_log.json", "w", encoding="utf-8") as f:
        json.dump(existing_logs, f, indent=2, ensure_ascii=False)

    print(f"Done! Saved {len(news)} 24-hr fresh news articles -> data/news.json")
    print(f"Done! Saved {len(jobs)} 24-hr fresh AI jobs -> data/jobs.json")


if __name__ == "__main__":
    asyncio.run(main())