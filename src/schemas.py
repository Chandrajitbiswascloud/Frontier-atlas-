from datetime import datetime, timezone
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


def utc_now_iso() -> str:
  return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SourceInfo(BaseModel):
  name: str
  url: str


# 1. Startup Entity
class StartupData(BaseModel):
  employeeCount: Optional[int] = Field(
      None, description="Number of employees if explicitly stated, else null"
  )


class StartupContent(BaseModel):
  entityName: str
  data: StartupData = Field(default_factory=StartupData)


class StartupEntity(BaseModel):
  schemaVersion: str = "1.0"
  recordType: Literal["STARTUP"] = "STARTUP"
  source: SourceInfo
  content: StartupContent
  collectedAt: str = Field(default_factory=utc_now_iso)


# 2. Product Entity
class ProductContent(BaseModel):
  startupName: str
  pricingModel: Literal["FREE", "FREEMIUM", "PAID", "ENTERPRISE"] = "FREEMIUM"


class ProductEntity(BaseModel):
  schemaVersion: str = "1.0"
  recordType: Literal["PRODUCT"] = "PRODUCT"
  source: SourceInfo
  content: ProductContent
  collectedAt: str = Field(default_factory=utc_now_iso)


# 3. Research Paper Entity
class ResearchPaperContent(BaseModel):
  title: str
  authors: List[str]
  paper_url: str
  github_url: Optional[str] = None
  github_stars: Optional[int] = None
  published_date: str


class ResearchPaperEntity(BaseModel):
  schemaVersion: str = "1.0"
  recordType: Literal["RESEARCH_PAPER"] = "RESEARCH_PAPER"
  content: ResearchPaperContent


# 4. Job Entity
class JobContent(BaseModel):
  company: str
  date: str
  is_remote: bool
  role_family: str


class JobEntity(BaseModel):
  schemaVersion: str = "1.0"
  recordType: Literal["JOB"] = "JOB"
  content: JobContent


# 5. News Entity
class NewsContent(BaseModel):
  title: str
  summary: str
  published_date: str
  entities_mentioned: List[str] = Field(default_factory=list)


class NewsEntity(BaseModel):
  schemaVersion: str = "1.0"
  recordType: Literal["NEWS"] = "NEWS"
  source: SourceInfo
  content: NewsContent
  collectedAt: str = Field(default_factory=utc_now_iso)


# 6. Entity Mapping Log
class EntityMappingLog(BaseModel):
  raw_name: str
  canonical_name: str
  confidence_score: float
  source_url: str
  logged_at: str = Field(default_factory=utc_now_iso)