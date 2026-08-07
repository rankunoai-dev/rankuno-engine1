# ADR 0002: `FullPageIntelligenceProfile` is the canonical Phase 1 output

- **Status**: Accepted
- **Date**: 2026-08-06
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

Two different Pydantic models are specified as the Phase 1 output, with overlapping
but non-identical fields:

| Model | Source | Distinctive fields |
| :--- | :--- | :--- |
| `FullPageIntelligenceProfile` | `PHASE1_PAGE_CLASSIFICATION_BLUEPRINT.md` §4, Infrastructure Proposal PDF p7 | `topical_category`, `sub_topic`, `search_intent`, `conversion_role`, `signals_evaluated`, `consensus_method` |
| `SiteNodeIntelligence` | Phase 1 Master Blueprint PDF (V2) §5 | `canonical_url`, `depth_from_l0`, `is_cross_silo_link`, `inbound_internal_links_count`, `outbound_internal_links_count`, `reasoning` |

`FullPageIntelligenceProfile` carries the three-interface classification (page type,
topical cluster, semantic intent) that the Phase 1 blueprint is built around.
`SiteNodeIntelligence` carries graph-topology fields that the first model lacks but
which Signal 5 (link in-degree centrality) and the tree visualizer both require.

Shipping both would mean two sources of truth for one concept.

## Decision

**`FullPageIntelligenceProfile` is the canonical output envelope.** `SiteNodeIntelligence`
is retired as a top-level contract.

The graph-topology fields it contributed are **absorbed** into
`FullPageIntelligenceProfile` rather than discarded, because Signal 5 and the tree
visualizer genuinely need them:

- `canonical_url` — required by SKU variant clustering.
- `depth_from_l0` — required to distinguish click depth from hierarchy level.
- `inbound_internal_links_count` / `outbound_internal_links_count` — Signal 5 inputs.
- `is_cross_silo_link` — topical silo analysis.

`reasoning` is **not** absorbed as free text. See Consequences.

`signals_evaluated: list[SignalScore]` is retained. It is what makes a classification
auditable and is required to debug consensus disagreements.

## Alternatives considered

1. **Keep both, with `SiteNodeIntelligence` as an internal graph record and
   `FullPageIntelligenceProfile` as the output DTO.** Rejected for Phase 1: two models
   that must be kept in sync is exactly the drift the Zero-Legacy principle exists to
   prevent. May be revisited if the graph record needs to persist independently.
2. **Adopt `SiteNodeIntelligence` and add the intent fields.** Rejected: the blueprint
   and the executive proposal both build on `FullPageIntelligenceProfile`, and it is the
   name leadership signed off on.

## Consequences

**Positive**

- One model, one source of truth, one set of tests.
- The output is self-describing: `signals_evaluated` plus `final_confidence_score`
  plus `consensus_method` explain every classification without a separate log lookup.

**Negative**

- The model is wide (roughly 18 fields). It must be composed from smaller sub-models
  rather than written flat.
- `reasoning` as LLM-generated free text is **deliberately excluded** from the LLM
  response schema. At Layer 3 output-token pricing, a prose field costs more than the
  entire page payload. If a rationale is needed, it must be a short bounded code, and
  the decision to add it requires its own ADR.

**Follow-up**

- Model lives at `src/modules/seo/page_classifier/schemas.py`.
- MUST inherit `StrictModel`. Confidence fields bounded `ge=0.0, le=1.0`.
- Taxonomy enums are UPPER_SNAKE per CLAUDE.md §7 ruling 3.
