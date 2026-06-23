Claude, I built v40.3 from the v40.2 Phase-1 engine and ran it on the real BTC Phase-1 logs.

Core result:
- v40.2: fired 4/25, correct 4/4, premises_used 4/4, wrong 0, fixed old-wrong = 3
- v40.3: fired 5/25, correct 5/5, premises_used 5/5, wrong 0, fixed old-wrong = 4

v40.3 replay report:
```json
{
  "n": 25,
  "fired": 5,
  "answer_correct": 5,
  "premises_used_correct": 5,
  "wrong": [],
  "fixed_old_wrong": ["T1_0023", "T1_0015", "T1_0007", "T1_0041"],
  "abstained": 20,
  "precision_when_fired": 1.0,
  "coverage": 0.2,
  "gate": "ABSTAIN_SAFE"
}
```

What changed in v40.3:
1. Added action-verb preservation for content verbs like capture/monitor/receive/provide/enter/require/recommend/administer/approve.
   - This fixes cases where "capture daytime images" became only `DaytimeImage` while the premise used `CaptureDaytimeImage`.
2. Added a conservative universal-relative rule parser:
   - `Every volunteer assigned to the morning triage shift receives a blue access badge` becomes `AssignedMorningShiftTriage -> ReceiveAccessBadgeBlue`.
   - `All satellites with high-resolution optical cameras can capture daytime images` becomes `CameraHighOpticalResolution -> CaptureDaytimeImage`.
3. Kept numeric literals in atom keys from v40.2; no regression to the earlier 12-vs-20 enrolled bug.
4. Kept abstain-safe gate: if multiple options or no single proof, return abstain.

Newly fixed old-wrong case:
- T1_0007 now fires correctly:
  - expected B
  - got B
  - premises_used [0, 3, 5, 6]
  - this was enabled by universal-relative rule parsing + action-verb preservation.

Existing fired cases remain correct:
- T1_0021 A, premises_used [0..9]
- T1_0023 A, premises_used [0,1,2,4,5,6,7]
- T1_0015 B, premises_used [0,1,3,4]
- T1_0041 A, premises_used [0,1,3,4,5]

Please critique:
1. Is the universal-relative rule parser too broad?
2. Are action verbs safe to preserve globally, or should they be a whitelist per verb family?
3. Should v40.3 be accepted as the new baseline since it increases fired count and preserves wrong=0 and premises_used correctness?
4. What should v40.4 target next among the remaining 20 abstains?

My proposed next target if v40.3 is accepted:
- v40.4: controlled alias map for predicate mismatch, especially:
  - eligible/use/can/may/allowed
  - approved/approval
  - requires/needs/review
  - recommended/recommendation
  - administered/administration
- But keep the hard gate: fired can increase only if wrong remains 0 and premises_used does not regress.
