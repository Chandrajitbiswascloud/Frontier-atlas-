import asyncio
import json
import os
import re
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
import httpx
from src.schemas import ResearchPaperContent, ResearchPaperEntity

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "FrontierAtlas-Pipeline",
}
if GITHUB_TOKEN:
  GITHUB_HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"


def extract_github_url(text: str) -> str | None:
  """Finds the first valid github.com/owner/repo URL inside a paper summary."""
  match = re.search(
      r"https?://github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)", text
  )
  if match:
    repo_path = match.group(1).rstrip(".,;:)")
    # Ignore generic github links that aren't repos
    if repo_path.split("/")[0].lower() not in {"topics", "orgs", "features"}:
      return f"https://github.com/{repo_path}"
  return None


async def fetch_github_stars(
    client: httpx.AsyncClient, github_url: str, semaphore: asyncio.Semaphore
) -> int | None:
  """Fetches live star count from GitHub API concurrently."""
  repo_path = github_url.replace("https://github.com/", "").strip("/")
  api_url = f"https://api.github.com/repos/{repo_path}"
  async with semaphore:
    try:
      resp = await client.get(api_url, headers=GITHUB_HEADERS, timeout=10.0)
      if resp.status_code == 200:
        return resp.json().get("stargazers_count")
    except Exception:
      pass
  return None


async def fetch_arxiv_batch(
    client: httpx.AsyncClient, start: int, max_results: int = 250
) -> list[dict]:
  """Fetches a batch of AI/ML research papers from ArXiv's official API."""
  url = (
      "https://export.arxiv.org/api/query?"
      f"search_query=cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL&start={start}&max_results={max_results}"
      "&sortBy=submittedDate&sortOrder=descending"
  )
  resp = await client.get(url, timeout=30.0)
  resp.raise_for_status()

  root = ET.fromstring(resp.text)
  ns = {"atom": "http://www.w3.org/2005/Atom"}
  raw_papers = []

  for entry in root.findall("atom:entry", ns):
    title = " ".join(entry.find("atom:title", ns).text.split())
    summary = " ".join(entry.find("atom:summary", ns).text.split())
    paper_url = entry.find("atom:id", ns).text.strip()
    published_date = entry.find("atom:published", ns).text.strip()
    authors = [
        author.find("atom:name", ns).text.strip()
        for author in entry.findall("atom:author", ns)
    ]
    github_url = extract_github_url(summary)

    raw_papers.append({
        "title": title,
        "authors": authors,
        "paper_url": paper_url,
        "github_url": github_url,
        "published_date": published_date,
    })
  return raw_papers


async def main():
  print("Fetching 1,100 AI research papers from ArXiv...")
  all_raw = []
  async with httpx.AsyncClient(follow_redirects=True) as client:
    # Fetch 1,100 papers in 5 clean batches so we comfortably exceed 1,000 unique rows
    for offset in range(0, 1100, 250):
      batch = await fetch_arxiv_batch(client, start=offset, max_results=250)
      all_raw.extend(batch)
      print(f"  Fetched {len(all_raw)} papers so far...")
      await asyncio.sleep(1.5)  # Polite delay for ArXiv API

    # Deduplicate by paper_url
    seen = set()
    unique_raw = []
    for p in all_raw:
      if p["paper_url"] not in seen:
        seen.add(p["paper_url"])
        unique_raw.append(p)

    print(
        f"Collected {len(unique_raw)} unique papers. Fetching GitHub stars"
        " concurrently..."
    )
    semaphore = asyncio.Semaphore(15)

    async def build_entity(item: dict) -> dict:
      stars = None
      if item["github_url"]:
        stars = await fetch_github_stars(client, item["github_url"], semaphore)
      entity = ResearchPaperEntity(
          content=ResearchPaperContent(
              title=item["title"],
              authors=item["authors"],
              paper_url=item["paper_url"],
              github_url=item["github_url"],
              github_stars=stars,
              published_date=item["published_date"],
          )
      )
      return entity.model_dump()

    results = await asyncio.gather(*(build_entity(p) for p in unique_raw))

  os.makedirs("data", exist_ok=True)
  with open("data/papers.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

  with_github = sum(1 for r in results if r["content"]["github_url"])
  print(f"Done! Saved {len(results)} unique papers to data/papers.json.")
  print(f"Papers with linked GitHub repositories: {with_github}")


if __name__ == "__main__":
  asyncio.run(main())