---
name: pydantic-schema-design
description: Procedural guide and architectural reference for designing Pydantic v2 data models, tool inputs/outputs, and settings schemas.
---

# 📐 Pydantic v2 Schema Design Standards

This skill details how data models, tool input schemas, API response payloads, and configuration settings MUST be defined across Rankuno's automation repositories.

---

## 🎯 Architectural Principles

1. **Type Safety & Strict Validation**: All data crossing component or network boundaries must be represented by a Pydantic `BaseModel`.
2. **Explicit Documentation**: Every model field MUST specify a clear `description` via `Field(...)`.
3. **Immutability & Frozen Defaults**: Core data contracts should use `model_config = ConfigDict(frozen=True)` to prevent unintended state mutation.
4. **JSON Schema Exportable**: Schemas must support standard JSON Schema generation for native MCP server integration.

---

## 📋 Schema Design Patterns & Examples

### 1. Base Tool Input Schema
```python
from pydantic import BaseModel, Field, HttpUrl


class SeoAuditInput(BaseModel):
    """Input payload for Technical SEO Audit Tool."""

    url: HttpUrl = Field(..., description="Target URL to audit for technical SEO compliance.")
    max_depth: int = Field(
        default=2, ge=1, le=10, description="Maximum link depth for site crawling."
    )
    check_mobile: bool = Field(
        default=True, description="Whether to perform mobile viewport rendering audit."
    )
```

### 2. Base Tool Output Schema
```python
from typing import List, Optional
from pydantic import BaseModel, Field


class SeoIssue(BaseModel):
    category: str = Field(..., description="Issue category (e.g., meta, speed, indexability).")
    severity: str = Field(..., description="Severity level: CRITICAL, WARNING, INFO.")
    message: str = Field(..., description="Human-readable description of the issue.")


class SeoAuditResult(BaseModel):
    target_url: str = Field(..., description="Audited URL.")
    score: float = Field(..., ge=0.0, le=100.0, description="Overall technical SEO health score.")
    issues: List[SeoIssue] = Field(default_factory=list, description="Discovered technical issues.")
    execution_time_ms: float = Field(..., description="Audit execution duration in milliseconds.")
```

---

## 🔒 Configuration & Secrets Schema
```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Global environment configuration schema."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = Field(default="development", description="Execution environment.")
    gsc_credentials_path: Optional[str] = Field(
        default=None, description="Path to Google Search Console service account key."
    )
    max_api_spend_limit_usd: float = Field(
        default=50.0, description="Daily API spend safety threshold."
    )
```
