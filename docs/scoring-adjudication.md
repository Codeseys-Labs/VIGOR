# VIGOR Scoring And Adjudication Policy

This document defines how reviewer outputs become accept, patch, branch, pivot, fail, or escalate decisions.

## Score Scale

All normalized scores use `0.0` to `1.0`, where `1.0` is best.

Adapters may ingest native scales, but must normalize them before adjudication.

| Native Scale | Normalization |
| --- | --- |
| 1 to 5 | `(score - 1) / 4` |
| 0 to 10 | `score / 10` |
| 0 to 100 | `score / 100` |
| pass/fail | pass = 1, fail = 0, plus hard-gate flag |
| cost/latency | invert only inside a named selection policy |

## Reviewer Types

| Type | Default Authority |
| --- | --- |
| Hard validator | Can block acceptance |
| Objective metric | Can block if threshold is configured |
| Learned scorer | Can rank and gate after calibration |
| LLM/VLM critic | Suggests patches and can gate subjective criteria by policy |
| Human reviewer | Can override automated selection when authorized |

## Hard Gates

Hard gates run before weighted scores.

Examples:

| Domain | Hard Gate |
| --- | --- |
| Code | Tests fail, build fails, typecheck fails |
| Video | Render error, illegible required text, missing required narration |
| Photo | Export failure, destructive identity edit when prohibited |
| CAD | Invalid solid, missing material/load metadata for load-bearing design |
| Robotics | Collision, forbidden zone, unsafe force |

If any hard gate fails, the candidate cannot be accepted unless a human explicitly overrides a non-safety gate.

## Weighted Composite

After hard gates pass, the adjudicator can compute a composite score.

```json
{
  "policy_id": "video.education.default.v1",
  "hard_gates": ["render_success", "text_legibility", "accessibility_required"],
  "weights": {
    "visual_quality": 0.20,
    "text_alignment": 0.25,
    "physical_consistency": 0.15,
    "education_clarity": 0.25,
    "accessibility": 0.15
  },
  "minimums": {
    "text_alignment": 0.65,
    "education_clarity": 0.70,
    "accessibility": 0.80
  }
}
```

## Disagreement Handling

Reviewer disagreement is a signal, not an error.

| Condition | Action |
| --- | --- |
| Objective validator fails, subjective reviewer likes output | Patch or fail; objective gate wins |
| Subjective reviewers disagree above threshold | Keep candidate, branch, or request human comparison |
| Learned scorer and VLM critic disagree | Inspect evidence; prefer reviewer calibrated for the target task |
| Human rejects high-scoring output | Store preference event and update calibration dataset |
| Scores plateau across iterations | Stop, branch, or choose best frontier candidate |

Disagreement threshold should be domain-specific. A useful default is `0.20` normalized-score spread between reviewers measuring the same dimension.

## Confidence And Calibration

Every reviewer should report confidence when possible. Confidence should not replace score, but can affect escalation.

Calibration data should include:

| Data | Use |
| --- | --- |
| Human A/B choices | Pairwise scorer calibration |
| Expert rubrics | Threshold and weighting design |
| Historical accepted artifacts | Style and quality priors |
| Failure cases | Hard-gate and patch policy tuning |
| Held-out benchmark tasks | Promotion decision for harness versions |

Learned scorers such as VideoScore2 should begin in shadow mode for a new domain. The framework should compare scorer choices with human or incumbent-reviewer decisions before making the scorer a hard gate.

## Adjudication Algorithm

```text
1. Validate that all required reviewers ran or record reviewer failure.
2. Apply hard gates.
3. Normalize reviewer scores to 0..1.
4. Check per-dimension minimum thresholds.
5. Compute weighted composite if policy requires it.
6. Measure reviewer disagreement and confidence.
7. Choose action: accept, patch, branch, pivot, fail, or escalate.
8. Write patch objectives or final selection reason.
9. Update frontier and provenance.
```

## Decision Actions

| Action | Meaning |
| --- | --- |
| accept | Candidate passes gates and is selected or eligible for final frontier selection |
| patch | Candidate is close enough to improve with targeted edits |
| branch | Candidate has competing directions worth exploring |
| pivot | Current direction is unlikely to satisfy goal |
| fail | Candidate should be rejected |
| escalate | Human, expert, or safety authority must decide |

## Best-Of-N Selection

Best-of-N should use the same hard gates and normalized score policies.

Selection order:

1. Remove candidates with non-overridable hard-gate failures.
2. Rank remaining candidates by primary policy score.
3. Break ties by editability, lower cost, and lower reviewer disagreement.
4. Preserve enough rejected-candidate metadata to audit selection.
5. Let authorized humans override when subjective preference is the final criterion.

## Example Adjudication Report

```json
{
  "adjudication_id": "adj_0009",
  "candidate_id": "cand_0004",
  "policy_id": "video.education.default.v1",
  "hard_gate_passed": true,
  "normalized_scores": {
    "visual_quality": 0.76,
    "text_alignment": 0.70,
    "physical_consistency": 0.68,
    "education_clarity": 0.81,
    "accessibility": 0.88
  },
  "composite": 0.77,
  "reviewer_disagreement": 0.12,
  "decision": "accept",
  "selection_reason": "Passes hard gates and beats other frontier candidates on education clarity and accessibility",
  "residual_risks": ["Physical consistency score is acceptable but not high"]
}
```
