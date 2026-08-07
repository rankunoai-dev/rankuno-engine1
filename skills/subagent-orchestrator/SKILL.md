---
name: subagent-orchestrator
description: Procedural skill for spawning, delegating tasks to, and synthesizing results from isolated Antigravity background subagents.
---

# 🤖 Subagent Delegation Protocol Skill

This skill defines the governance and execution guidelines for spawning subagents (`invoke_subagent` and `browser_subagent`) within Rankuno's AI Automation Infrastructure.

---

## 🎯 Strategic Delegation Framework

Subagents are isolated execution contexts used to perform focused tasks without consuming main agent context window or interrupting primary orchestration logic.

```
                  ┌─────────────────────────────────────────┐
                  │          PRIMARY ORCHESTRATOR           │
                  └────────────────────┬────────────────────┘
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            │                          │                          │
            ▼                          ▼                          ▼
   ┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
   │ RESEARCH AGENT  │        │   CODE REVIEW   │        │ BROWSER AUDITOR │
   │  (Subagent 1)   │        │   (Subagent 2)  │        │  (Subagent 3)   │
   ├─────────────────┤        ├─────────────────┤        ├─────────────────┤
   │ - SERP Scraping │        │ - Security Audit│        │ - Technical SEO │
   │ - Competitor    │        │ - Pydantic Check│        │ - DOM Rendering │
   │   Analysis      │        │ - Test Gate Run │        │ - Mobile Test   │
   └────────┬────────┘        └────────┬────────┘        └────────┬────────┘
            │                          │                          │
            └──────────────────────────┼──────────────────────────┘
                                       │
                                       ▼
                  ┌─────────────────────────────────────────┐
                  │      SYNTHESIZED EXECUTIVE REPORT       │
                  └─────────────────────────────────────────┘
```

---

## 📋 When to Spawn Subagents

1. **Heavy Domain Research**: Isolated web scraping, keyword data collection, SERP analysis.
2. **Dedicated Code Review & Security Audit**: Running comprehensive static analysis, Pydantic schema validation, and test checks.
3. **Headless Visual & Technical SEO Audits**: Launching `browser_subagent` for JavaScript rendering, DOM structure inspection, or mobile layout validation.
4. **Parallel Task Execution**: Running independent exploratory tasks concurrently.

---

## ⚙️ Subagent Spawn Best Practices

1. **Clear & Self-Contained Prompt**: Provide full background, exact expected outputs, target paths, and exit conditions.
2. **Explicit Artifact Output**: Request subagents to write structured findings to `<appDataDir>\brain\<conversation-id>\` or designated output paths.
3. **No Unbounded Polling**: Never poll subagent status in a tight loop. Rely on background notifications or one-shot `schedule` timers.
4. **Result Synthesis**: Upon completion, read subagent findings, synthesize key takeaways, and update the main implementation plan.
