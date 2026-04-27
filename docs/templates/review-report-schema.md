# Review Report Schema

VIGOR reviewers must return structured reports so the adjudicator can reason over evidence.

## Review Report

```json
{
  "review_id": "review_0001",
  "candidate_id": "cand_0007",
  "artifact_id": "artifact_preview_0007",
  "reviewer": {
    "id": "photo.histogram.v1",
    "type": "objective_metric",
    "model": null,
    "tool_version": "0.1.0"
  },
  "summary": "Highlights are within tolerance, but foreground blacks are slightly crushed.",
  "scores": {
    "overall": 0.78,
    "highlight_safety": 0.92,
    "shadow_detail": 0.61
  },
  "thresholds": {
    "overall_min": 0.70,
    "shadow_detail_min": 0.65
  },
  "passed": false,
  "confidence": 0.84,
  "findings": [
    {
      "id": "finding_0001",
      "severity": "medium",
      "category": "tonality",
      "artifact_ref": "preview.jpg",
      "location": {
        "type": "region",
        "label": "foreground rocks",
        "bbox": [0, 740, 1600, 1060]
      },
      "evidence": "6.8 percent of pixels in foreground mask are below luma 3/255.",
      "rule_or_rubric": "Protect shadows unless the style explicitly asks for crushed blacks.",
      "suggestion": "Raise foreground shadows by 5 to 10 or lift black point locally.",
      "verified_by_tool": true
    }
  ],
  "recommended_action": "patch",
  "metadata": {
    "runtime_ms": 210,
    "input_hashes": ["sha256:..."],
    "created_at": "2026-04-26T00:00:00Z"
  }
}
```

## Severity

| Severity | Meaning |
| --- | --- |
| high | Blocks acceptance or indicates safety/correctness risk |
| medium | Should be fixed before final if budget allows |
| low | Nice-to-have improvement |
| info | Observation only |

## Recommended Actions

| Action | Meaning |
| --- | --- |
| accept | Candidate passes according to this reviewer |
| patch | Candidate can be fixed with targeted changes |
| branch | Candidate direction is promising but should split alternatives |
| pivot | Candidate is fundamentally off direction |
| escalate | Human or higher-authority review required |
| fail | Candidate should be rejected |

## Adjudication Report

```json
{
  "adjudication_id": "adj_0003",
  "candidate_id": "cand_0007",
  "decision": "patch",
  "basis": ["review_0001", "review_0002", "review_0005"],
  "hard_gate_failures": ["shadow_detail_min"],
  "reviewer_disagreement": {
    "present": true,
    "summary": "Aesthetic critic prefers moodier shadows, but histogram critic flags detail loss. Preserve mood while lifting foreground minimally."
  },
  "patch_objectives": [
    "Lift foreground black point locally without changing global contrast",
    "Do not brighten cabin further",
    "Keep warm grade unchanged"
  ],
  "stop_reason": null,
  "frontier_update": {
    "keep_candidate": true,
    "rank": 2,
    "notes": "Strong style candidate despite shadow issue"
  }
}
```
