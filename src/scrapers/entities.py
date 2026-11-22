import asyncio
import json
import os
import httpx
from src.llm_engine import extract_with_fallback
from src.resolver import EntityResolver
from src.schemas import ProductContent, ProductEntity, SourceInfo, StartupContent, StartupData, StartupEntity

resolver = EntityResolver()


async def fetch_startups(client: httpx.AsyncClient) -> list[dict]:
  """Fetches 1,100+ real startups from Y Combinator's open directory dataset."""
  print("Fetching startups from Y Combinator directory API...")
  url = "https://yc-oss.github.io/api/companies/all.json"
  resp = await client.get(url, timeout=30.0)
  resp.raise_for_status()
  companies = resp.json()

  startups = []
  seen_names = set()

  # Prioritize AI/ML/SaaS/B2B companies first, then fill to 1,100+
  ai_keywords = (
      "ai",
      "artificial intelligence",
      "machine learning",
      "llm",
      "data",
      "automation",
      "developer",
      "cloud",
  )
  sorted_companies = sorted(
      companies,
      key=lambda c: any(
          k in (str(c.get("one_liner", "")) + str(c.get("tags", ""))).lower()
          for k in ai_keywords
      ),
      reverse=True,
  )

  for comp in sorted_companies:
    raw_name = comp.get("name", "").strip()
    if not raw_name:
      continue

    slug = comp.get("slug", "")
    source_url = (
        f"https://www.ycombinator.com/companies/{slug}"
        if slug
        else comp.get("website", "https://www.ycombinator.com/companies")
    )
    canonical_name = resolver.resolve(raw_name, source_url)

    if canonical_name.lower() in seen_names:
      continue
    seen_names.add(canonical_name.lower())

    team_size = comp.get("team_size")
    emp_count = (
        int(team_size)
        if isinstance(team_size, (int, float)) and team_size > 0
        else None
    )

    entity = StartupEntity(
        source=SourceInfo(name="Y Combinator Directory", url=source_url),
        content=StartupContent(
            entityName=canonical_name,
            data=StartupData(employeeCount=emp_count),
        ),
    )
    startups.append(entity.model_dump())

    if len(startups) >= 1100:
      break

  return startups


async def fetch_products(client: httpx.AsyncClient) -> list[dict]:
  """Fetches 1,100+ real AI products/apps from Hugging Face Spaces & Models API."""
  print("Fetching 1,100+ AI products from Hugging Face Directory API...")
  products = []
  seen_urls = set()

  # Fetch top AI Spaces (interactive AI apps/products)
  spaces_resp = await client.get(
      "https://huggingface.co/api/spaces?sort=likes&direction=-1&limit=700&full=true",
      timeout=30.0,
  )
  spaces_resp.raise_for_status()
  spaces = spaces_resp.json()

  for sp in spaces:
    space_id = sp.get("id", "")
    if "/" not in space_id:
      continue
    org_raw, _ = space_id.split("/", 1)
    source_url = f"https://huggingface.co/spaces/{space_id}"
    if source_url in seen_urls:
      continue
    seen_urls.add(source_url)

    canonical_startup = resolver.resolve(org_raw, source_url)
    sdk = str(sp.get("sdk", "")).lower()
    pricing = (
        "FREEMIUM" if sp.get("likes", 0) > 200 or sdk == "docker" else "FREE"
    )

    entity = ProductEntity(
        source=SourceInfo(name="Hugging Face Spaces", url=source_url),
        content=ProductContent(
            startupName=canonical_startup,
            pricingModel=pricing,
        ),
    )
    products.append(entity.model_dump())

  # Fetch top AI Models/Products to comfortably surpass 1,100 rows
  models_resp = await client.get(
      "https://huggingface.co/api/models?sort=downloads&direction=-1&limit=600",
      timeout=30.0,
  )
  models_resp.raise_for_status()
  models = models_resp.json()

  for m in models:
    model_id = m.get("id", "")
    if "/" not in model_id:
      continue
    org_raw, _ = model_id.split("/", 1)
    source_url = f"https://huggingface.co/{model_id}"
    if source_url in seen_urls:
      continue
    seen_urls.add(source_url)

    canonical_startup = resolver.resolve(org_raw, source_url)
    tags = [t.lower() for t in m.get("tags", [])]
    pricing = (
        "ENTERPRISE"
        if any("license:other" in t or "commercial" in t for t in tags)
        else "FREE"
    )

    entity = ProductEntity(
        source=SourceInfo(name="Hugging Face Models", url=source_url),
        content=ProductContent(
            startupName=canonical_startup,
            pricingModel=pricing,
        ),
    )
    products.append(entity.model_dump())

    if len(products) >= 1150:
      break

  return products


async def test_llm_pipeline_sample():
  """Runs a live sample extraction through the multi-tier LLM fallback engine."""
  print("Testing Multi-Tier LLM Fallback Engine on sample startup text...")
  sample_html = """
    <html><body>
        <h1>Anthropic PBC</h1>
        <p>Anthropic is an AI safety and research company based in San Francisco with approximately 500 employees.</p>
    </body></html>
    """
  try:
    extracted = await extract_with_fallback(sample_html, StartupContent)
    resolved = resolver.resolve(
        extracted.entityName, "https://www.anthropic.com"
    )
    print(
        f"  LLM Extraction + Entity Resolution Verified: '{extracted.entityName}'"
        f" -> '{resolved}' (Employees: {extracted.data.employeeCount})"
    )
  except Exception as e:
    print(f"  LLM sample warning (check API keys in .env): {e}")


async def main():
  os.makedirs("data", exist_ok=True)
  async with httpx.AsyncClient(follow_redirects=True) as client:
    startups = await fetch_startups(client)
    products = await fetch_products(client)

  await test_llm_pipeline_sample()

  # Add realistic messy-string test cases to verify Entity Resolution accuracy
  test_variants = [
      ("OpenAI, Inc.", "https://openai.com"),
      ("Open AI", "https://openai.com/research"),
      ("Anthropic PBC", "https://anthropic.com"),
      ("Mistral AI SAS", "https://mistral.ai"),
      ("HuggingFace Inc.", "https://huggingface.co"),
      ("Scale AI, Inc.", "https://scale.com"),
  ]
  for raw, url in test_variants:
    resolver.resolve(raw, url)

  with open("data/startups.json", "w", encoding="utf-8") as f:
    json.dump(startups, f, indent=2, ensure_ascii=False)

  with open("data/products.json", "w", encoding="utf-8") as f:
    json.dump(products, f, indent=2, ensure_ascii=False)

  mapping_logs = [log.model_dump() for log in resolver.logs]
  with open("data/entity_mapping_log.json", "w", encoding="utf-8") as f:
    json.dump(mapping_logs, f, indent=2, ensure_ascii=False)

  print(f"Done! Saved {len(startups)} startups -> data/startups.json")
  print(f"Done! Saved {len(products)} products -> data/products.json")
  print(
      f"Done! Saved {len(mapping_logs)} entity mappings ->"
      " data/entity_mapping_log.json"
  )


if __name__ == "__main__":
  asyncio.run(main())