---
name: Feature / Tool Request
about: Request a new automation capability. Triggers SDLC Step 1.
title: "[Feature] "
labels: ["needs-investigation"]
---

## The manual workflow being automated

<!-- Describe what a human does today, step by step. This is the raw input to
     SDLC Step 1 (Investigation & Requirement Discovery). Be concrete: which
     tools, which screens, which exports. -->

## Frequency and volume

<!-- How often is this run, and over how many URLs / keywords / accounts?
     This determines rate-limit and cost design, not just performance. -->

## Inputs

<!-- What does the operator supply? Domain, keyword list, GSC property, CSV? -->

## Expected output

<!-- What artifact should exist when the tool finishes? A report, a CSV, a
     ranked list, a content brief? Who consumes it? -->

## Risk classification

- [ ] **READ** — analysis only, no side effects
- [ ] **DRAFT** — generates something a human reviews before use
- [ ] **WRITE** — changes live client state
- [ ] **FINANCIAL** — spends money

## External services required

<!-- APIs, scrapers, data providers. Note any known quota or pricing. -->

## Definition of done

<!-- How will we know this works? What would you check first? -->
