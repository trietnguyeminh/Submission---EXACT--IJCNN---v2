# ynu_meta_unknown_certificate.py — YNU-only explicit no-premise -> Uncertain. Live-safe, very narrow.
# -*- coding: utf-8 -*-
# Holdout-verified: 779 YNU + 838 MC, 0 spurious, 0 MC fire (PROMOTE_TO_DEPLOY).
# Fires ONLY when: request is YNU AND a premise is "No premise states whether/that X"
#                  AND atom(X) == atom(question target). Else returns None (keep LoRA/v35 baseline).
# Disabled by design: Yes proof, No proof, semantic alias, partial meta, pruning.
# Requires engine name in scope: to_literal  (and module-level re).

import re

_YNU = {"yes", "no", "unknown", "uncertain"}

def _is_ynu(options):
    return (not options) or set(str(o).strip().lower() for o in options) <= _YNU

def _strip_question(q):
    s = str(q or "").strip().rstrip("?").strip()
    s = re.sub(r",?\s+according to the premises\.?$", "", s, flags=re.I).strip()
    s = re.sub(r"^\s*do(?:es)?\s+the\s+premises\s+(?:prove|establish|show)\s+that\s+", "", s, flags=re.I)
    s = re.sub(r"^\s*do(?:es)?\s+having\s+", "having ", s, flags=re.I)
    s = re.sub(r"^\s*(does|do|did)\s+", "", s, flags=re.I)
    s = re.sub(r"^\s*(is|are|was|were)\s+", "", s, flags=re.I)
    s = re.sub(r"^\s*(can|could|may|might|must|should|will|would)\s+", "", s, flags=re.I)
    return s.strip()

def _meta_claim(premise):
    s = str(premise).strip().rstrip(".")
    m = re.search(r"^\s*no premise states\s+(?:whether|that)\s+(.+)$", s, flags=re.I)
    return m.group(1).strip() if m else None

def ynu_meta_unknown_cert(question, premises, options):
    """Return cert dict or None. YNU-only; explicit no-premise; atom-matched."""
    if not _is_ynu(options):
        return None
    ql = to_literal(_strip_question(question))
    if not ql:
        return None
    qa, _ = ql
    for i, p in enumerate(premises):
        mc = _meta_claim(p)
        if not mc:
            continue
        ml = to_literal(mc)
        if ml and ml[0] == qa:
            return {"answer": "Uncertain", "premises_used": [i],
                    "cert_type": "explicit_no_premise", "source_premise": str(p)}
    return None

def ynu_meta_prehandler(req, field):
    """Pipeline pre-handler: returns a /predict Type1 response dict, or None to fall through to LoRA."""
    q = field(req, "query", "") or ""
    premises = list(field(req, "premises", []) or [])
    options = list(field(req, "options", []) or [])
    c = ynu_meta_unknown_cert(q, premises, options)
    if c is None:
        return None
    return {"query_id": field(req, "query_id", "unknown"), "answer": "Uncertain", "unit": "",
            "explanation": "YNU explicit no-premise statement -> Uncertain.",
            "premises_used": c["premises_used"], "reasoning": {"source": "ynu_meta_unknown_cert"}}
