# Score opportunity

**Machine** portfolio · **State** `scored` · **Kind** AI-assisted · **Role** analysis
**Inputs** `opportunity`, `claim` · **Outputs** `evaluation`

Turns an opportunity into a comparable number, without pretending the number is more than
it is.

## Procedure

1. **Resolve the scoring model.** Default is `core/reference/scoring/portfolio-default.v1.yaml`.
   Record its id, version, and content hash in the evaluation. A model that changed
   underneath an evaluation makes that evaluation unexplainable, which is why the hash is
   not optional.

2. **Score each dimension in the model.** For each:
   - Find the claims that support a value. Put their ids in `evidence_refs`.
   - Record the `raw` measurement in the dimension's own unit, then the `normalized` 0-1
     value produced by the model's normalizer.
   - Set `tier` from the supporting claims. **Empty `evidence_refs` forces
     `hypothesis`** — this is the mechanism, not a guideline.
   - If the tier is weaker than the dimension's `min_evidence_tier`, set
     `below_min_evidence_tier`. It does not block; it gets raised at the gate.

3. **Apply the evidence policy.** Hypothesis-tier dimensions carry reduced weight
   (`hypothesis_weight_multiplier`, default 0.5). Not zero: zeroing them would push
   scorers to invent citations. Not full: that would make guessing free.

4. **Compute `evidence_coverage`** — the share of total weight carried by evidence-backed
   dimensions. This is the number that makes "well-evidenced" checkable at G1.

5. **Evaluate vetoes.** Record every veto result by id, including the ones that did not
   fire. A veto is non-compensatory: it rejects regardless of aggregate. This is why the
   model uses a weighted sum rather than a geometric mean — a sum plus three named vetoes
   is explainable in one sentence at a gate, and a geometric mean is not.

6. **Aggregate**, then write a `ranking_note` saying why this sits where it does relative
   to the rest of the shortlist. That note is what the human actually reads.

7. **Append, never overwrite.** Re-scoring writes a new evaluation with
   `supersedes_evaluation_id` set. Keeping the history is what lets you re-score the
   backlog under a new model and diff the rankings to see what a weight change really did.

## Exit

- `above_shortlist_threshold` + `evidence_coverage_met` + `no_veto_fired` → `shortlisted`
- otherwise → `rejected`, recording which condition failed
- evidence older than `evidence_ttl_days` → `stale`

## Failure modes

- **Scoring to a conclusion.** If the dimensions are adjusted until the favoured
  opportunity wins, the model is decoration. Score first, then look at the ranking.
- **Precision theatre.** `0.6432` from four hypotheses is not more accurate than `0.6`. The
  tier and coverage fields carry the honesty; the aggregate carries the ordering.
- **Ignoring the rejected set.** The vetoes that fired on other candidates are part of the
  story at G1 and should not be quietly dropped.
