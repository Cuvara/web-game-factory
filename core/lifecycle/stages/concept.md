# Concept

**Machine** title · **State** `concept` · **Kind** automatic · **Role** analysis
**Inputs** `opportunity`, `evaluation` · **Outputs** none

A title record is created from a promoted opportunity. Mechanical and brief.

## Procedure

1. Allocate a `title_id` — kebab-case, stable for the life of the title, and used in every
   artifact path from here on.
2. Create `workspace/titles/<title-id>/` with an initial `state.json`.
3. **Pin the inputs by hash.** The opportunity and its latest evaluation go into the
   title's provenance chain with their `content_hash` recorded. This is what makes it
   detectable later that the market read behind this title has been superseded — the check
   that runs on resume from `paused` and that stops a title quietly shipping against a
   belief the factory no longer holds.
4. Copy the opportunity's claim refs forward so strategy can cite them without
   re-discovering them.

## Exit

Immediate: `draft_strategy` → `strategy`. There is no gate here; G1 already decided this
title should exist.
