# atom representation v2 — findings & conclusion (gated on real holdout)

Datasets: Phase-1 (25, entity-grounded, the SCORED distribution) + cleaned_v2 (608) + v5_repair (784) + aug_holdout (200 canary).
Gate = parser_patch_gate.py (verified-gain-only; fp_delta diagnostic). Baseline = engine_v40_snapshot.py.

## All candidates tried — every one REJECT or NOOP on real data
| candidate | mechanism | Phase-1 | cleaned_v2 | v5_repair | verdict |
|---|---|---|---|---|---|
| (Kaggle surface-rule) | When/Any item/That + split consequent | ACCEPT_NOOP | ACCEPT_NOOP | ACCEPT_NOOP | NOOP (PROMOTE on aug only) |
| atomv2a_scaffold | add all/every/any/one/exist/least/there/who… to STOP | ACCEPT_NOOP | REJECT 16 gain / 25 wrong / 5 ambig | — | REJECT |
| atomv2b_existonly | strip exist/least/there/who only | ACCEPT_NOOP | REJECT 0 gain / 1 wrong | REJECT 0 gain / 2 wrong | REJECT |
| atomv2c_structural | existential-frame + if-comma-rule + universal-fact (parse-level) | ACCEPT_NOOP | REJECT 4 lost / 3 gain / fp-5 | REJECT 5 lost + 4 wrong / 3 gain | REJECT |

## Why it doesn't work — distribution mismatch (the key insight)
Inspecting the holdout premises shows cleaned_v2/v5_repair are a DIFFERENT, HARDER question type than Phase-1:
- They ask **"which statement can be inferred?"** where the OPTIONS are themselves compound **rules** (rule-inference / rule-composition).
- Phase-1 is **entity-grounded** (does THIS entity have property P) — the engine's actual sweet spot.

So the 326 holdout `key_mismatch` are largely an OUT-OF-SCOPE reasoning type, not a canonicalization win for the scored distribution. Any broad atom change:
- churns the fire set on the rule-inference holdout (gains a few, loses/wrongs a few → net REJECT), and
- does NOTHING on Phase-1 (ACCEPT_NOOP every time).

Phase-1's own remaining MC gaps (the 4 `not_derivable`: aerial-corridor, no-take-zone, badge, open-science) need genuine **rule-chaining** to derive the consequent atom — not atom representation. Even perfect canonicalization wouldn't fire them.

## Conclusion: FREEZE atom representation v2
Four gated candidates, four non-promotions. The gate proves there is no safe net-positive atom/parser change with this approach on the real distribution. MC symbolic coverage is at/near its ceiling for this engine architecture on Phase-1. Pushing further would require a different (rule-inference) architecture — large effort, high overfit risk, low Phase-1 payoff. Not worth it pre-deadline.

The banked, gate-verified gains stand:
- v40 symbolic engine (already deployed): fires 5/25 Phase-1 MC, precision 1.0.
- cert v3 (+2.0pp Type1, frozen).
- YNU meta-unknown cert (+4.0pp Type1, holdout-verified 0 spurious, integrated into Account B).

Rejected candidate engines (atomv2a/b/c_*.py) are kept for the record only — DO NOT DEPLOY.

## Status
- MC cert v3: FROZEN
- v40 symbolic: deployed
- YNU meta-unknown: integrated into Account B (endpoint full-gate to run on Kaggle)
- YNU Yes/No proof: OFF (needs rule-inference engine, not atom v2)
- 1B pruning: WAITING (and now lower priority — pruning needs strict contradicted, also engine-limited)
- atom representation v2: FROZEN (4 gated candidates, none promotable; distribution-mismatch)
