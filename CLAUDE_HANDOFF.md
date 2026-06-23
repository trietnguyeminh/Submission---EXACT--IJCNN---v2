# Claude handoff — EXACT Phase-1 v40.5 one-run audit

## Context
We are hardening an abstain-safe symbolic certificate layer for EXACT Phase-1 Type1. Current engine is an entity-grounded conjunctive Horn forward-chain solver. It should override the model only when it has a unique proof certificate.

Source mode for this run: `replay_cases_only`.

## Current result summary
- All cases n: 25
- Fired: 5
- Abstained: 20
- Fired accuracy: 1.0
- Strict accuracy if abstain is wrong: 0.2
- MC fired/total: 5/13
- YNU fired/total: 0/12

## Important verdict
Do NOT broaden by heuristic tie-break. Keep T1_0031-like `multiple` cases as abstain. Current value is precision/certificate safety, not coverage.

## Underfit / overfit
- Underfit is high because coverage is low: ALL abstains=20/25, MC abstains=8/13, YNU abstains=12/12.
- Classic overfit cannot be measured from replay cases alone. Risk becomes high only if new parser rules are tuned directly to the same 25 cases without a full-log/holdout gate.

## Requested next action for Claude
Review `exact_v40_5_one_run_pipeline.py` and the stage JSON files. Improve only by adding certificate-preserving parser rules. Any candidate must output stage JSON and pass:

```python
wrong == []
answer_correct == fired
premises_used_correct does not regress
```

Never promote a YNU heuristic unless the full `exact_eval_round1_Astatine.json` verifies it. If full log is unavailable, keep YNU as audit-only.
