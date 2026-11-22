import re
from rapidfuzz import fuzz, process
from src.schemas import EntityMappingLog

# Seed list of 55+ known canonical AI startups
CANONICAL_AI_STARTUPS = [
    "OpenAI",
    "Anthropic",
    "Mistral AI",
    "Hugging Face",
    "Cohere",
    "Scale AI",
    "Perplexity AI",
    "Runway",
    "Midjourney",
    "Stability AI",
    "Databricks",
    "Together AI",
    "Groq",
    "Fireworks AI",
    "Anyscale",
    "Weights & Biases",
    "Pinecone",
    "Weaviate",
    "Qdrant",
    "Chroma",
    "LangChain",
    "LlamaIndex",
    "Harvey",
    "Glean",
    "Sierra",
    "Cognition",
    "Cursor",
    "Replit",
    "Vercel",
    "Supabase",
    "ElevenLabs",
    "HeyGen",
    "Synthesia",
    "Suno",
    "Udio",
    "Character.AI",
    "Inflection AI",
    "Adept",
    "xAI",
    "DeepSeek",
    "Aleph Alpha",
    "AI21 Labs",
    "Reka AI",
    "Imbue",
    "Poolside",
    "Magic",
    "Contextual AI",
    "Snorkel AI",
    "Labelbox",
    "Turing",
    "Mercor",
    "Vapi",
    "Bland AI",
    "Retell AI",
    "Mem0",
]

SUFFIX_PATTERN = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|pbc|co|company|technologies|technology|labs)\b\.?",
    flags=re.IGNORECASE,
)


def normalize_string(name: str) -> str:
  cleaned = SUFFIX_PATTERN.sub("", name)
  cleaned = re.sub(r"[^\w\s.&-]", "", cleaned)
  return " ".join(cleaned.split()).strip()


class EntityResolver:

  def __init__(self, threshold: float = 84.0):
    self.threshold = threshold
    self.canonical_list = CANONICAL_AI_STARTUPS
    self.logs: list[EntityMappingLog] = []

  def resolve(self, raw_name: str, source_url: str) -> str:
    if not raw_name or not raw_name.strip():
      return "Unknown"

    raw_clean = raw_name.strip()
    stripped = normalize_string(raw_clean)

    # Exact case-insensitive match first
    for canon in self.canonical_list:
      if (
          stripped.lower() == canon.lower()
          or raw_clean.lower() == canon.lower()
      ):
        if raw_clean != canon:
          self.logs.append(
              EntityMappingLog(
                  raw_name=raw_clean,
                  canonical_name=canon,
                  confidence_score=100.0,
                  source_url=source_url,
              )
          )
        return canon

    # Fuzzy match against canonical seed list
    match = process.extractOne(
        stripped, self.canonical_list, scorer=fuzz.WRatio
    )
    if match and match[1] >= self.threshold:
      canonical_name, score, _ = match
      if raw_clean != canonical_name:
        self.logs.append(
            EntityMappingLog(
                raw_name=raw_clean,
                canonical_name=canonical_name,
                confidence_score=round(float(score), 2),
                source_url=source_url,
            )
        )
      return canonical_name

    # If not in seed list, return title-cased clean name and log if modified
    fallback_name = stripped if stripped else raw_clean
    if raw_clean != fallback_name:
      self.logs.append(
          EntityMappingLog(
              raw_name=raw_clean,
              canonical_name=fallback_name,
              confidence_score=90.0,
              source_url=source_url,
          )
      )
    return fallback_name