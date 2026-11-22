# FrontierAtlas — AI Ecosystem Intelligence Pipeline

An asynchronous, fault-tolerant data ingestion, enrichment, and entity-resolution pipeline built to extract structured intelligence across AI startups, products, research papers, live job postings, and real-time news signals.

## Architecture Overview

1. **Asynchronous Acquisition (`src/scrapers/`):**
   - `papers.py`: Concurrently queries ArXiv APIs for AI/ML research papers, extracts linked GitHub repositories, and enriches records with live star counts via the GitHub REST API.
   - `entities.py`: Acquires structured startup records and AI product catalogs with non-blocking HTTP concurrency (`httpx.AsyncClient` + `asyncio.Semaphore`).
   - `signals.py`: Monitors 5 AI news feeds and 5 AI job boards concurrently, enforcing strict 24-hour freshness via `dateparser` UTC normalization and SHA-256 URL hash deduplication.
   - `antibot_demo.py`: Demonstrates headless Playwright browser rendering with randomized profiles, asset blocking, and optional proxy routing for JS-heavy domains.
2. **Multi-Tier LLM Orchestrator (`src/llm_engine.py`):**
   - Strips boilerplate HTML tags (`<script>`, `<style>`, `<nav>`, `<footer>`) and truncates payloads to prevent `413 Payload Too Large` errors.
   - Routes extraction across a 3-tier fallback chain (**Gemini Flash → Groq Llama → DeepSeek**) with exponential backoff and random jitter to handle `429 Too Many Requests`.
   - Enforces strict Pydantic schema validation (`src/schemas.py`) with explicit `null` handling to eliminate hallucinated fields.
3. **Deterministic Entity Resolution (`src/resolver.py`):**
   - Normalizes corporate suffixes (`Inc.`, `LLC`, `PBC`, `Ltd.`, `Labs`) and applies `rapidfuzz` WRatio matching against a canonical seed registry, logging raw-to-canonical mappings.

## Setup & Execution

### 1. Environment Setup
```bash
python -m venv venv
# Windows PowerShell:
.\venv\Scripts\Activate.ps1
# Linux/macOS:
source venv/bin/activate

pip install httpx beautifulsoup4 pydantic python-dotenv rapidfuzz dateparser google-genai groq openai feedparser playwright
playwright install chromium