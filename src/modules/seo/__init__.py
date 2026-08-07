"""SEO Automation Engine - the first domain pillar.

Planned scope (see `docs/ROADMAP.md`); nothing is implemented yet:

* `audit.py` - technical SEO crawl and DOM extraction
* `keyword_cluster.py` - semantic keyword embedding and intent clustering
* `brief_generator.py` - AI content brief generation
* `rank_tracker.py` - Google Search Console rank synthesis

Every tool added here must subclass `src.core.BaseTool`, declare a `RiskClass`,
ship unit tests with external calls mocked, and enter via the 8-step SDLC loop in
`docs/SDLC_GUIDELINES.md`.
"""
