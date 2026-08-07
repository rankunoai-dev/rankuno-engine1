# 🤖 Phase 7: AI Answer Visibility Engine Blueprint (AEO & GEO Optimization)

> **Document ID**: `RKN-P7-2026-V1`  
> **Prepared By**: AI Lead  
> **Effective Date**: July 31, 2026  
> **Parent Standard**: `RKN-STD-2026-V1`  
> **Status**: DRAFT — Pending HITL Architecture Review (§14 Step 3)  

---

## 1. Executive Overview & Purpose

Search behavior is bifurcating. A growing share of discovery queries now begin — and end — inside a conversational AI interface rather than a traditional search results page. When an engine like ChatGPT, Perplexity, Gemini, or Google's AI Overview answers a user directly, it either cites a client's page as a source, paraphrases it without a link, or omits it entirely in favor of a competitor.

Phase 7 extends the Rankuno Agentic Platform Stack (§4 of `RKN-STD-2026-V1`) with a fourth classification interface sitting alongside Page Type, Topical Cluster, and Semantic Intent from Phase 1: **Cross-Engine AI Answer Visibility**.

---

## 2. The 3-Interface AI Visibility Framework

```
                    Client Brand / URL Set / Topic List
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
        ▼                          ▼                          ▼
┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐
│ INTERFACE 1:         │ │ INTERFACE 2:         │ │ INTERFACE 3:         │
│ Cross-Engine Citation│ │ Answer-Readiness     │ │ Competitive Share-of-│
│ Detection            │ │ Audit                │ │ Voice & Prompt Gap   │
├──────────────────────┤ ├──────────────────────┤ ├──────────────────────┤
│ - Direct Citation     │ │ - llms.txt Presence  │ │ - Named Competitor   │
│ - Mentioned, No Link  │ │ - Schema.org / JSON- │ │   Prompt Overlap     │
│ - Not Mentioned       │ │   LD Coverage        │ │ - Share-of-Voice %   │
│ - Competitor Cited    │ │ - Crawler Access Log │ │ - Prompt-Gap List    │
│   Instead             │ │   (GPTBot/ClaudeBot) │ │ - Sentiment Delta    │
└──────────────────────┘ └──────────────────────┘ └──────────────────────┘
```

---

## 3. The 6-Signal AI Visibility Consensus Architecture

1. **Signal 1: Direct Prompt-Response Query**: BYOK queries issued to ChatGPT, Claude, Perplexity, Gemini, Copilot, Grok, Meta AI, DeepSeek with rotating brand-injection tokens.
2. **Signal 2: Search-Grounding Citation Extraction**: Direct extraction of cited-source lists from Gemini Grounding and Google AI Overview panels.
3. **Signal 3: Crawler Access Log Analysis**: Edge log audit for GPTBot, ClaudeBot, ChatGPT-User, PerplexityBot, Google-Extended, Bytespider.
4. **Signal 4: AI-Readability Schema Audit**: Static audit of `llms.txt`, `llms-full.txt`, Schema.org JSON-LD (Article, FAQPage, Product, Organization).
5. **Signal 5: Competitor Prompt-Gap Benchmarking**: Same prompt set evaluated against up to 5 named competitor brands.
6. **Signal 6: LLM Accuracy & Sentiment Classifier**: Secondary LLM pass evaluating factual accuracy, sentiment, and entity disambiguation.

---

## 4. Pydantic Data Contracts (`StrictModel`)

```python
from enum import Enum
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class AIEngine(str, Enum):
    CHATGPT = "CHATGPT"
    CLAUDE = "CLAUDE"
    PERPLEXITY = "PERPLEXITY"
    GEMINI = "GEMINI"
    GOOGLE_AI_OVERVIEW = "GOOGLE_AI_OVERVIEW"
    GOOGLE_AI_MODE = "GOOGLE_AI_MODE"
    COPILOT = "COPILOT"
    GROK = "GROK"
    META_AI = "META_AI"
    DEEPSEEK = "DEEPSEEK"


class CitationType(str, Enum):
    DIRECT_CITATION = "DIRECT_CITATION"
    MENTIONED_NO_LINK = "MENTIONED_NO_LINK"
    NOT_MENTIONED = "NOT_MENTIONED"
    COMPETITOR_CITED_INSTEAD = "COMPETITOR_CITED_INSTEAD"


class VisibilitySentiment(str, Enum):
    ACCURATE_POSITIVE = "ACCURATE_POSITIVE"
    ACCURATE_NEUTRAL = "ACCURATE_NEUTRAL"
    ACCURATE_NEGATIVE = "ACCURATE_NEGATIVE"
    INACCURATE = "INACCURATE"
    OUTDATED = "OUTDATED"


class CitationRecord(BaseModel):
    engine: AIEngine
    probe_id: str
    citation_type: CitationType
    cited_url: Optional[str]
    position_in_answer: Optional[int]
    sentiment: VisibilitySentiment
    response_hash: str  # SHA-256 hash of response, never raw text


class FullAnswerVisibilityProfile(BaseModel):
    brand: str
    url_scope: List[str]
    probes_evaluated: List[dict]
    citation_records: List[CitationRecord]
    competitor_benchmarks: List[dict]
    signals_evaluated: List[dict]
    answer_readiness_score: float = Field(ge=0.0, le=1.0)
    final_confidence_score: float = Field(ge=0.0, le=1.0)
    consensus_method: str
```

---

*Maintained by the AI Lead & Engineering Team at Rankuno.*
