"""Local HTTP API exposing the governed tools to the React UI.

The outermost layer. Dependencies point inward only:
`api -> modules -> integrations -> core` (CLAUDE.md §1). Nothing below imports
from here.

This layer adds no analysis of its own. It is a transport: it validates a
request, hands it to a `BaseTool`, and persists the result. Every safety
control — SSRF validation, robots compliance, throttling, guardrails, audit
logging — is inherited from the tool, not reimplemented here. An endpoint that
reached around `BaseTool.run()` would bypass all of it at once.
"""
