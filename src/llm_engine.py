import asyncio
import json
import os
import random
from typing import Type, TypeVar
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google import genai
from groq import AsyncGroq
from openai import AsyncOpenAI
from pydantic import BaseModel

load_dotenv()

T = TypeVar("T", bound=BaseModel)

gemini_client = (
    genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    if os.getenv("GEMINI_API_KEY")
    else None
)
groq_client = (
    AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
    if os.getenv("GROQ_API_KEY")
    else None
)
deepseek_client = (
    AsyncOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
    )
    if os.getenv("DEEPSEEK_API_KEY")
    else None
)

_CACHED_GROQ_MODEL: str | None = None


def clean_and_chunk_html(raw_html: str, max_chars: int = 12000) -> str:
  """Removes scripts/styles/nav junk and truncates to prevent 413 Payload Too Large."""
  soup = BeautifulSoup(raw_html, "html.parser")
  for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
    tag.decompose()
  clean_text = " ".join(soup.get_text(separator=" ").split())
  return clean_text[:max_chars]


async def _call_gemini(prompt: str) -> str:
  if not gemini_client:
    raise RuntimeError("GEMINI_API_KEY not set")
  response = await asyncio.to_thread(
      gemini_client.models.generate_content,
      model="gemini-3.8-flash",
      contents=prompt,
      config={"response_mime_type": "application/json"},
  )
  return response.text


async def _get_active_groq_model() -> str:
  """Dynamically queries Groq for an active Llama/Qwen chat model enabled on this key."""
  global _CACHED_GROQ_MODEL
  if _CACHED_GROQ_MODEL:
    return _CACHED_GROQ_MODEL
  models_page = await groq_client.models.list()
  available = [
      m.id
      for m in models_page.data
      if "whisper" not in m.id.lower() and "guard" not in m.id.lower()
  ]
  for preferred in ("llama-4", "llama-3.3", "llama-3.1", "qwen", "gemma"):
    for mid in available:
      if preferred in mid.lower():
        _CACHED_GROQ_MODEL = mid
        return mid
  if available:
    _CACHED_GROQ_MODEL = available[0]
    return available[0]
  raise RuntimeError("No active chat models available on Groq key")


async def _call_groq(prompt: str) -> str:
  if not groq_client:
    raise RuntimeError("GROQ_API_KEY not set")
  model_id = await _get_active_groq_model()
  resp = await groq_client.chat.completions.create(
      model=model_id,
      messages=[{"role": "user", "content": prompt}],
      response_format={"type": "json_object"},
      temperature=0.0,
  )
  return resp.choices[0].message.content


async def _call_deepseek(prompt: str) -> str:
  if not deepseek_client:
    raise RuntimeError("DEEPSEEK_API_KEY not set")
  resp = await deepseek_client.chat.completions.create(
      model="deepseek-chat",
      messages=[{"role": "user", "content": prompt}],
      response_format={"type": "json_object"},
      temperature=0.0,
  )
  return resp.choices[0].message.content


async def extract_with_fallback(
    raw_html: str, schema_cls: Type[T], max_retries: int = 3
) -> T:
  """Tries Gemini -> Groq -> DeepSeek with exponential backoff + jitter on 429 errors."""
  cleaned_text = clean_and_chunk_html(raw_html)
  schema_json = json.dumps(schema_cls.model_json_schema(), indent=2)

  prompt = (
      "You are a strict data extraction engine. Extract structured data from "
      "the text below matching the exact JSON schema provided.\n"
      "CRITICAL RULES:\n"
      "1. NEVER guess or hallucinate missing numbers, dates, or names.\n"
      "2. If a field is not explicitly stated in the text, return null.\n"
      "3. Output ONLY valid JSON matching this schema:\n"
      f"{schema_json}\n\n"
      f"SOURCE TEXT:\n{cleaned_text}"
  )

  providers = [
      ("Gemini Flash", _call_gemini),
      ("Groq Llama", _call_groq),
      ("DeepSeek", _call_deepseek),
  ]

  last_error = None
  for provider_name, call_fn in providers:
    for attempt in range(max_retries):
      try:
        raw_json = await call_fn(prompt)
        return schema_cls.model_validate_json(raw_json)
      except Exception as e:
        last_error = e
        err_msg = str(e).lower()
        if "429" in err_msg or "rate" in err_msg or "503" in err_msg:
          sleep_time = (2 ** (attempt + 1)) + random.uniform(0.2, 1.2)
          print(
              f"[{provider_name}] Rate limited. Retrying in {sleep_time:.2f}s..."
          )
          await asyncio.sleep(sleep_time)
        else:
          print(f"[{provider_name}] Failed ({e}). Switching provider...")
          break

  raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")