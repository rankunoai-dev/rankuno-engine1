"""Governed Screaming Frog CLI process control (ADR 0013 conditions 4-8).

Conditions 1-3 — the Windows Job Object + independent ledger + reconciliation
primitive this package launches through — live in `src.core.process_supervisor`
and are documented there. This package is what turns that primitive into a
`RiskClass.WRITE`, `MANDATORY_HITL` tool: the seed-URL `UrlSafetyPolicy` gate,
the `.seospiderconfig` template-by-name mapping, positive licence
verification, and the governed entry point itself.
"""

from __future__ import annotations

__all__: list[str] = []
