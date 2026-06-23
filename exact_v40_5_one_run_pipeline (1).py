# -*- coding: utf-8 -*-
"""
EXACT Phase-1 v40.5 one-run audit + safe-upgrade pipeline.

What it does in one command:
1) Finds exact_eval_round1_Astatine.json when available.
2) Replays the current abstain-safe v40.4/v40.5 MC certificate engine.
3) Writes JSON for every stage: input audit, current pipeline, replay, gap audit,
   metrics, overfit/underfit audit, safe-upgrade decision, and Claude handoff data.
4) If full Phase-1 logs are absent, falls back to v40_4_phase1_replay_cases.json
   and computes all metrics that are possible from the replay cases.

Design principle: never promote a wider rule unless it keeps wrong=[] and does not
regress answer/premises correctness. YNU experimental support is audited but not
blindly applied unless a full log verifies it safely.
"""
from __future__ import annotations

import argparse
import copy
import glob
import importlib.util
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

VERSION = "v40.5-one-run-safe-audit"
MC_LABELS = ["A", "B", "C", "D"]
YNU_LABELS = ["Yes", "No", "Uncertain"]
ALL_LABELS = MC_LABELS + YNU_LABELS
ABSTAIN = "__ABSTAIN__"

# ---------------------------------------------------------------------------
# v40.4/v40.5 conservative entity-grounded conjunctive Horn engine
# ---------------------------------------------------------------------------
STOP = {
    'a','an','the','of','to','in','on','at','for','and','or','that','this','their','its','it','they','them',
    'is','are','was','were','be','been','has','have','had','then','if','no','not','with','as','by','from',
    'artifact','package','manuscript','sample','batch','item','device','record','file','student','case',
    'premise','premises','according','conclusion','logically','supported','correct','statement','based'
}

def _stem(t: str) -> str:
    if re.search(r'(ss|us|is)$', t):
        return t
    if re.search(r'(ches|shes|xes|zes|ses)$', t):
        return t[:-2]
    if re.search(r'ies$', t):
        return t[:-3] + 'y'
    if t.endswith('s'):
        t = t[:-1]
    return re.sub(r'(ing|ed)$', '', t)

def atom_key(phrase: Any) -> Optional[str]:
    s = re.sub(r'(?<!^)(?=[A-Z])', ' ', str(phrase)).lower()
    nums = re.findall(r'\d+', s)
    toks = [_stem(w) for w in re.findall(r'[a-zA-Z]+', s)]
    toks = [t for t in toks if t and t not in STOP and len(t) > 2]
    keys = sorted(set(toks)) + ["N" + n for n in sorted(set(nums))]
    return "".join(w.capitalize() for w in keys) if keys else None

_LEAD = re.compile(r"^\s*(if|then|that|who|which|it|its|their|this)\b", re.I)
_VERB = re.compile(
    r"\b(cannot|can not|can|could|may|might|must|should|shall|will|would|"
    r"is not|are not|was not|were not|isn't|aren't|is|are|was|were|"
    r"has no|have no|had no|has|have|had|lacks?|without|"
    r"requires?|needs?|contains?|completed?|enters?|gains?|receives?|provides?|"
    r"shows?|states?|holds?|carries|monitors?|captures?|eligible|allowed|approved|"
    r"assigned|listed|qualifies?|qualified|searchable|recommended|administered|"
    r"displayed|dispatch(?:ed)?|review(?:ed)?|released?|closed|"
    r"be|been|being)\b", re.I
)
ACTION_VERBS = {
    'receives','receive','provides','provide','shows','show','states','state','monitors','monitor','captures','capture',
    'enters','enter','requires','require','needs','need','gains','gain','completed','complete','contains','contain',
    'reports','report','releases','release','passes','pass','improves','improve','supports','support','recommends',
    'recommend','administered','administer','approved','approve','listed','list','qualifies','qualify','qualified',
    'searchable','displayed','display','dispatch','dispatched','review','reviewed','released','release','closed','close'
}
_NEG_RE = re.compile(
    r"\b(no|not|cannot|can not|never|lacks?|without|isn't|aren't|incomplete|missing|lacking|nor|"
    r"un(?:able|verified|established|approved|cleared|safe|eligible))\b", re.I
)

def to_literal(clause: Any) -> Optional[Tuple[str, bool]]:
    c = str(clause).strip().rstrip('.?').strip()
    c = _LEAD.sub('', c).strip()
    # normalize common question fragments into declarative-ish clauses
    c = re.sub(r"^does\s+(.+?)\s+have\s+(.+)$", r"\1 has \2", c, flags=re.I)
    c = re.sub(r"^do\s+the\s+premises\s+(?:prove|establish|show|guarantee)\s+that\s+", "", c, flags=re.I)
    neg = bool(_NEG_RE.search(c))
    m = _VERB.search(c)
    pred = c[m.end():].strip() if m else c
    verb = (m.group(1).lower() if m else '')
    if m and verb in ACTION_VERBS:
        pred = verb + ' ' + pred
    for _ in range(5):
        pred = re.sub(r"^\s*(be|been|being|to|a|an|the|no|not|its|their|for|by)\b", "", pred, flags=re.I).strip()
    a = atom_key(pred)
    return (a, neg) if a else None

def parse_premise(p: Any) -> Optional[Tuple]:
    s = str(p).strip()
    m = re.search(r'^\s*if\b(.+?),?\s*\bthen\b(.+)$', s, re.I)
    if m:
        ante = re.split(r'\band\b', m.group(1), flags=re.I)
        lits = [to_literal(x) for x in ante]
        lits = [l for l in lits if l]
        con = to_literal(m.group(2))
        if con and lits:
            return ('rule', lits, con)
        return None
    m2 = re.search(
        r'^\s*(every|all)\s+[a-zA-Z]+s?\s+(.+?)\s+\b(can|may|must|should|will|would|receives?|gets?|gains?|provides?|captures?|monitors?|requires?|needs?|is|are|qualifies?|eligible|listed|recommended)\b\s+(.+)$',
        s, re.I,
    )
    if m2:
        cond = m2.group(2).strip()
        cons = (m2.group(3) + " " + m2.group(4)).strip()
        litc = to_literal(cond)
        litd = to_literal(cons)
        if litc and litd:
            return ('rule', [litc], litd)
    if re.search(r'^\s*(no premise|it (is|cannot)|unknown|there is no information)', s, re.I):
        return None
    lit = to_literal(s)
    return ('fact', lit) if lit else None

def solve_entity(premises: Sequence[Any]) -> Dict[str, Tuple[bool, List[int]]]:
    facts: Dict[str, Tuple[bool, List[int]]] = {}
    rules = []
    for i, p in enumerate(premises):
        pp = parse_premise(p)
        if not pp:
            continue
        if pp[0] == 'fact':
            a, neg = pp[1]
            facts.setdefault(a, (not neg, [i]))
        else:
            rules.append((i, pp[1], pp[2]))
    changed = True
    while changed:
        changed = False
        for i, lits, con in rules:
            ca, cneg = con
            ok = True
            path = [i]
            for a, neg in lits:
                if a in facts and facts[a][0] == (not neg):
                    path += facts[a][1]
                else:
                    ok = False
                    break
            if ok and ca not in facts:
                facts[ca] = ((not cneg), sorted(set(path)))
                changed = True
    return facts

_META_RE = re.compile(
    r"\b(not (?:yet )?(?:established|confirmed|verified|approved|cleared|determined)|"
    r"cannot be (?:established|confirmed)|unsupported|is not established|no premise|undetermined|not (?:available|present))\b",
    re.I,
)

def decompose_option(opt: Any) -> List[Tuple[Optional[Tuple[str, bool]], bool, str]]:
    t = re.sub(r'^\s*[A-Da-d][.):]\s*', '', str(opt)).strip()
    t = re.split(r'\bbecause\b', t, maxsplit=1, flags=re.I)[0].strip()
    parts = re.split(r',\s*but\s+|\s+but\s+|;\s+|\s+while\s+|\s+whereas\s+|\s+and\s+', t, flags=re.I)
    claims = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        is_meta = bool(_META_RE.search(p))
        lit = to_literal(p)
        claims.append((lit, is_meta, p))
    return claims

def answer_mc(premises: Sequence[Any], options: Sequence[Any]) -> Tuple[Optional[str], List[int], str, Dict[str, Tuple[str, List[int]]]]:
    facts = solve_entity(premises)
    res: Dict[str, Tuple[str, List[int]]] = {}
    for lab, opt in zip("ABCD", options):
        claims = decompose_option(opt)
        if not claims:
            res[lab] = ('UNSUP', [])
            continue
        status = 'PROVEN'
        path: List[int] = []
        for lit, is_meta, txt in claims:
            if lit is None:
                status = 'UNSUP'
                break
            a, neg = lit
            have = a in facts
            val = facts[a][0] if have else None
            if is_meta:
                if have and val is True:
                    status = 'DISPROVEN'
                    break
            else:
                if have and val == (not neg):
                    path += facts[a][1]
                elif have and val == neg:
                    status = 'DISPROVEN'
                    break
                else:
                    status = 'UNSUP'
                    break
        res[lab] = (status, sorted(set(path)))
    proven = [l for l in res if res[l][0] == 'PROVEN']
    if len(proven) == 1:
        return proven[0], res[proven[0]][1], 'entity_unique_proof', res
    return None, [], ('multiple' if proven else 'none'), res

# Experimental target parser for YNU. It is audited but not promoted unless verified.
_PROOF_NEGATIVE_Q = re.compile(r"\b(premises\s+(?:prove|establish|show)|establish|prove|guarantee|satisfy every requirement)\b", re.I)

def question_to_claim(query: Any) -> Tuple[Optional[Tuple[str, bool]], str]:
    q = str(query).strip()
    q = re.sub(r"\s+", " ", q).strip().rstrip('?')
    q = re.sub(r",\s*according to the premises", "", q, flags=re.I)
    q = re.sub(r"\s+according to the premises", "", q, flags=re.I)
    mode = "direct_unknown_absence"
    if _PROOF_NEGATIVE_Q.search(q):
        mode = "proof_absence_means_no"
    # Peel question shells.
    patterns = [
        r"^do\s+the\s+premises\s+(?:prove|establish|show|guarantee)\s+that\s+(.+)$",
        r"^is\s+(.+)$",
        r"^are\s+(.+)$",
        r"^does\s+(.+)$",
        r"^do\s+(.+)$",
        r"^can\s+(.+)$",
        r"^may\s+(.+)$",
        r"^must\s+(.+)$",
        r"^should\s+(.+)$",
    ]
    claim = None
    for pat in patterns:
        m = re.search(pat, q, flags=re.I)
        if m:
            claim = m.group(1).strip()
            break
    if claim is None:
        claim = q
    # Convert simple auxiliaries.
    claim = re.sub(r"^(.+?)\s+have\s+(.+)$", r"\1 has \2", claim, flags=re.I)
    lit = to_literal(claim)
    return lit, mode

def answer_ynu_experimental(premises: Sequence[Any], query: Any) -> Tuple[Optional[str], List[int], str, Dict[str, Any]]:
    lit, mode = question_to_claim(query)
    facts = solve_entity(premises)
    debug = {"target_literal": lit, "mode": mode}
    if lit is None:
        return None, [], "ynu_no_target", debug
    a, neg = lit
    if a in facts:
        val, path = facts[a]
        if val == (not neg):
            return "Yes", path, "ynu_target_proven", debug
        if val == neg:
            return "No", path, "ynu_target_disproven", debug
    # Conservative: only proof-form questions may map absence of proof to No.
    # Direct property questions stay Uncertain only when a known uncertainty cue exists in premises.
    if mode == "proof_absence_means_no":
        return "No", [], "ynu_proof_absence_means_no_no_certificate", debug
    return None, [], "ynu_direct_absence_abstain", debug

def opt_texts(rp: Dict[str, Any]) -> List[str]:
    query = rp.get("query", "") or ""
    found = re.findall(r"(?:^|\n)\s*([A-D])[.)]\s*(.+?)(?=\n\s*[A-D][.)]|\Z)", query, flags=re.S)
    f = [text.strip().replace("\n", " ") for _, text in found]
    return f if len(f) >= 2 else (rp.get("options") or [])

def classify_task(expected_answer: Any, query: str = "", options: Optional[Sequence[Any]] = None) -> str:
    ea = str(expected_answer).strip()
    if ea.upper() in MC_LABELS:
        return "MC"
    if ea in YNU_LABELS:
        return "YNU"
    opts = options or []
    if len(opts) >= 2:
        return "MC"
    if re.match(r"^(is|are|do|does|can|may|must|should)\b", str(query).strip(), flags=re.I):
        return "YNU"
    return "OTHER"

# ---------------------------------------------------------------------------
# Data loading and replay
# ---------------------------------------------------------------------------
def find_phase1(explicit: Optional[str] = None) -> Optional[str]:
    if explicit and os.path.exists(explicit):
        return explicit
    patterns = [
        "exact_eval_round1_Astatine.json",
        "./exact_eval_round1_Astatine.json",
        "/kaggle/working/**/exact_eval_round1_Astatine.json",
        "/kaggle/input/**/exact_eval_round1_Astatine.json",
        "/mnt/data/**/exact_eval_round1_Astatine.json",
    ]
    hits: List[str] = []
    for pat in patterns:
        if any(ch in pat for ch in "*?"):
            hits.extend(glob.glob(pat, recursive=True))
        elif os.path.exists(pat):
            hits.append(pat)
    hits = sorted(set(hits))
    return hits[0] if hits else None

def load_phase1_logs(path: str) -> List[Dict[str, Any]]:
    data = json.load(open(path, encoding="utf-8"))
    logs = [l for l in data.get("logs", []) if l.get("type") == "type1"]
    return logs

def run_variant_on_logs(logs: Sequence[Dict[str, Any]], variant: str) -> List[Dict[str, Any]]:
    rows = []
    for l in logs:
        rp = l.get("request_payload", {}) or {}
        exp = l.get("expected", {}) or {}
        expected_answer = exp.get("answer")
        task = classify_task(expected_answer, rp.get("query", ""), rp.get("options"))
        premises = rp.get("premises", []) or []
        options = opt_texts(rp)
        a: Optional[str] = None
        pu: List[int] = []
        why = "not_run"
        res: Dict[str, Any] = {}
        if task == "MC":
            a, pu, why, res = answer_mc(premises, options)
        elif task == "YNU" and variant == "mc_plus_ynu_experimental":
            a, pu, why, res = answer_ynu_experimental(premises, rp.get("query", ""))
        else:
            a, pu, why, res = None, [], "task_abstain", {}
        ea_norm = str(expected_answer or "").strip()
        ans_ok = a is not None and str(a).strip().upper() == ea_norm.upper()
        prem_ok = a is not None and sorted(pu) == sorted(exp.get("premises_used") or [])
        rows.append({
            "query_id": l.get("query_id"),
            "task": task,
            "old_status": l.get("status"),
            "expected_answer": expected_answer,
            "expected_premises_used": exp.get("premises_used"),
            "v_answer": a,
            "v_premises_used": pu,
            "rule": why,
            "answer_ok": ans_ok,
            "premises_ok": prem_ok,
            "query": str(rp.get("query", ""))[:500],
            "option_status": res,
        })
    return rows

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def safe_div(a: float, b: float) -> Optional[float]:
    return None if b == 0 else a / b

def round_float(x: Any, nd: int = 6) -> Any:
    if isinstance(x, float):
        return round(x, nd)
    return x

def classification_metrics(rows: Sequence[Dict[str, Any]], labels: Sequence[str], pred_key: str = "v_answer") -> Dict[str, Any]:
    n = len(rows)
    correct = 0
    fired = 0
    per = {}
    for lab in labels:
        tp = fp = fn = 0
        support = 0
        for r in rows:
            y = str(r.get("expected_answer", "")).strip()
            p = r.get(pred_key)
            p = str(p).strip() if p is not None else ABSTAIN
            if y == lab:
                support += 1
            if p != ABSTAIN:
                fired += 0  # counted once below
            if p == lab and y == lab:
                tp += 1
            elif p == lab and y != lab:
                fp += 1
            elif p != lab and y == lab:
                fn += 1
        precision = safe_div(tp, tp + fp)
        recall = safe_div(tp, tp + fn)
        f1 = None if precision is None or recall is None or (precision + recall) == 0 else 2 * precision * recall / (precision + recall)
        per[lab] = {
            "support": support,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round_float(precision) if precision is not None else None,
            "recall": round_float(recall) if recall is not None else None,
            "f1": round_float(f1) if f1 is not None else None,
        }
    fired = sum(1 for r in rows if r.get(pred_key) is not None)
    correct = sum(1 for r in rows if str(r.get(pred_key, "")).strip().upper() == str(r.get("expected_answer", "")).strip().upper())
    # Macro treats undefined precision/F1 as 0 for strict abstain-as-miss scoring.
    macro_precision = sum((per[l]["precision"] or 0.0) for l in labels) / len(labels) if labels else None
    macro_recall = sum((per[l]["recall"] or 0.0) for l in labels) / len(labels) if labels else None
    macro_f1 = sum((per[l]["f1"] or 0.0) for l in labels) / len(labels) if labels else None
    return {
        "n": n,
        "fired": fired,
        "abstained": n - fired,
        "coverage": round_float(safe_div(fired, n) or 0.0),
        "strict_accuracy_abstain_as_wrong": round_float(safe_div(correct, n) or 0.0),
        "fired_accuracy": round_float(safe_div(correct, fired)) if fired else None,
        "macro_precision_strict": round_float(macro_precision),
        "macro_recall_strict": round_float(macro_recall),
        "macro_f1_strict": round_float(macro_f1),
        "per_label": per,
    }

def baseline_status_metrics(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    c = Counter(r.get("old_status") for r in rows)
    exact_correct = c.get("correct", 0)
    answer_correct = c.get("correct", 0) + c.get("wrong_premises_used", 0)
    by_label = defaultdict(lambda: Counter())
    for r in rows:
        by_label[str(r.get("expected_answer"))][r.get("old_status")] += 1
    label_recall = {}
    for lab, cnt in by_label.items():
        support = sum(cnt.values())
        label_recall[lab] = {
            "support": support,
            "old_exact_recall_by_status": round_float(safe_div(cnt.get("correct", 0), support) or 0.0),
            "old_answer_recall_by_status": round_float(safe_div(cnt.get("correct", 0) + cnt.get("wrong_premises_used", 0), support) or 0.0),
            "status_counts": dict(cnt),
        }
    return {
        "n": n,
        "status_counts": dict(c),
        "old_exact_accuracy_status_correct_only": round_float(safe_div(exact_correct, n) or 0.0),
        "old_answer_accuracy_status_correct_or_wrong_premises": round_float(safe_div(answer_correct, n) or 0.0),
        "note": "F1/precision for the old model require raw old predicted labels; status-only cases cannot reconstruct them.",
        "per_expected_label_status_recall": label_recall,
    }

def apply_override_status(rows: Sequence[Dict[str, Any]], pred_key: str = "v_answer") -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        x = copy.deepcopy(r)
        old = r.get("old_status")
        if r.get(pred_key) is None:
            x["applied_status"] = old
        else:
            if r.get("answer_ok") and r.get("premises_ok"):
                x["applied_status"] = "correct"
            elif r.get("answer_ok"):
                x["applied_status"] = "wrong_premises_used"
            else:
                x["applied_status"] = "wrong_answer"
        out.append(x)
    return out

def applied_status_metrics(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    c = Counter(r.get("applied_status") for r in rows)
    exact_correct = c.get("correct", 0)
    answer_correct = c.get("correct", 0) + c.get("wrong_premises_used", 0)
    return {
        "n": n,
        "status_counts_after_safe_override": dict(c),
        "estimated_exact_accuracy_after_override": round_float(safe_div(exact_correct, n) or 0.0),
        "estimated_answer_accuracy_after_override": round_float(safe_div(answer_correct, n) or 0.0),
        "note": "This estimate is exact for status categories if old_status semantics are correct. Label F1 still needs raw old predictions for abstained rows.",
    }

def split_rows(rows: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "ALL": list(rows),
        "MC": [r for r in rows if classify_task(r.get("expected_answer"), r.get("query", "")) == "MC" or r.get("task") == "MC"],
        "YNU": [r for r in rows if classify_task(r.get("expected_answer"), r.get("query", "")) == "YNU" or r.get("task") == "YNU"],
    }

def full_metrics(rows: Sequence[Dict[str, Any]], source_note: str) -> Dict[str, Any]:
    groups = split_rows(rows)
    out = {"source_note": source_note, "groups": {}}
    for name, rs in groups.items():
        labels = MC_LABELS if name == "MC" else YNU_LABELS if name == "YNU" else ALL_LABELS
        applied = apply_override_status(rs)
        out["groups"][name] = {
            "baseline_status_metrics": baseline_status_metrics(rs),
            "certificate_engine_metrics": classification_metrics(rs, labels),
            "after_safe_override_status_metrics": applied_status_metrics(applied),
        }
    return out

def replay_report_from_rows(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    fired_rows = [r for r in rows if r.get("v_answer") is not None or r.get("v40_answer") is not None]
    # support both raw v40 cases and new rows
    def get_answer(r): return r.get("v_answer", r.get("v40_answer"))
    def get_pu(r): return r.get("v_premises_used", r.get("v40_premises_used", []))
    wrong = []
    fixed = []
    aok = pok = 0
    for r in rows:
        a = get_answer(r)
        if a is None:
            continue
        ok = str(a).strip().upper() == str(r.get("expected_answer", "")).strip().upper()
        prem_ok = sorted(get_pu(r)) == sorted(r.get("expected_premises_used") or [])
        aok += int(ok)
        pok += int(prem_ok)
        if ok and r.get("old_status") != "correct":
            fixed.append(r.get("query_id"))
        if not ok:
            wrong.append({"query_id": r.get("query_id"), "exp": r.get("expected_answer"), "got": a})
    return {
        "n": len(rows),
        "fired": len(fired_rows),
        "answer_correct": aok,
        "premises_used_correct": pok,
        "wrong": wrong,
        "fixed_old_wrong": fixed,
        "abstained": len(rows) - len(fired_rows),
        "precision_when_fired": round_float(safe_div(aok, len(fired_rows))) if fired_rows else None,
        "coverage": round_float(safe_div(len(fired_rows), len(rows)) or 0.0),
        "gate": "ABSTAIN_SAFE" if not wrong else "HAS_WRONG_FIX_BEFORE_APPLY",
    }

# ---------------------------------------------------------------------------
# JSON/report writing
# ---------------------------------------------------------------------------
def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def normalize_uploaded_cases(cases: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for r in cases:
        x = dict(r)
        x["task"] = classify_task(x.get("expected_answer"), x.get("query", ""))
        x["v_answer"] = x.get("v40_answer")
        x["v_premises_used"] = x.get("v40_premises_used", [])
        rows.append(x)
    return rows

def make_gap_audit(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    groups = split_rows(rows)
    out = {}
    for name, rs in groups.items():
        abst = [r for r in rs if r.get("v_answer") is None and r.get("v40_answer") is None]
        fired = [r for r in rs if r.get("v_answer") is not None or r.get("v40_answer") is not None]
        out[name] = {
            "n": len(rs),
            "fired": len(fired),
            "abstained": len(abst),
            "abstain_rate": round_float(safe_div(len(abst), len(rs)) or 0.0),
            "old_status_counts_in_abstains": dict(Counter(r.get("old_status") for r in abst)),
            "expected_answer_counts_in_abstains": dict(Counter(str(r.get("expected_answer")) for r in abst)),
            "top_abstain_examples": [
                {"query_id": r.get("query_id"), "expected_answer": r.get("expected_answer"), "old_status": r.get("old_status"), "rule": r.get("rule"), "query": r.get("query", "")[:180]}
                for r in abst[:12]
            ],
        }
    return out

def make_current_pipeline_json(source_mode: str) -> Dict[str, Any]:
    return {
        "version": VERSION,
        "source_mode": source_mode,
        "pipeline": [
            {"stage": 0, "name": "input_audit", "description": "Find full Phase-1 log if available; otherwise use uploaded replay cases."},
            {"stage": 1, "name": "parse_task", "description": "Split Type1 into MC labels A-D and YNU labels Yes/No/Uncertain."},
            {"stage": 2, "name": "entity_horn_solver", "description": "Parse facts/rules into single-entity literals; forward-chain Horn implications; retain certificate premise indices."},
            {"stage": 3, "name": "mc_certificate_answer", "description": "For A-D options, prove/decompose claims; fire only on exactly one PROVEN option."},
            {"stage": 4, "name": "ynu_experimental_audit", "description": "YNU target parser is audited only; not promoted unless full-log gate has zero wrong and no premises regression."},
            {"stage": 5, "name": "safe_override", "description": "Override existing model only when certificate answer is non-null and gate passes; otherwise keep original model output."},
            {"stage": 6, "name": "metrics_and_gap_audit", "description": "Write coverage, fired precision, status accuracy, F1/recall where reconstructable, abstain breakdown, overfit/underfit risk."},
        ],
        "hard_gate": {
            "must_have_wrong_empty": True,
            "must_have_all_fired_answers_correct": True,
            "must_not_regress_premises_used_correct": True,
            "on_fail": "reject_candidate_and_keep_previous_stage",
        },
    }

def make_overfit_underfit_audit(rows: Sequence[Dict[str, Any]], source_mode: str) -> Dict[str, Any]:
    gap = make_gap_audit(rows)
    report = replay_report_from_rows(rows)
    mc_n = gap["MC"]["n"]
    ynu_n = gap["YNU"]["n"]
    return {
        "version": VERSION,
        "source_mode": source_mode,
        "summary": {
            "overfit_status": "inconclusive_from_replay_only" if source_mode != "phase1_log" else "needs_holdout_or_cross_log_check",
            "underfit_status": "high_coverage_underfit",
            "why": [
                "The rule layer is not trained statistically, so classic train-loss/test-loss overfit cannot be measured from this artifact alone.",
                "Overfit risk appears when rules are hand-tuned to the same 25 Phase-1 cases; use staged zero-wrong promotion and a separate holdout/full log.",
                f"Underfit/low-coverage is visible: fired={report['fired']}/{report['n']} and abstained={report['abstained']}/{report['n']}.",
                f"MC abstains={gap['MC']['abstained']}/{mc_n}; YNU abstains={gap['YNU']['abstained']}/{ynu_n}.",
            ],
        },
        "risk_scores_qualitative": {
            "current_v40_4_overfit_risk": "low_to_medium_because_rules_are_broad_but_validated_on_small_n",
            "future_parser_expansion_overfit_risk": "medium_to_high_unless_checked_on_full_log_or_holdout",
            "current_underfit_risk": "high_because_coverage_is_low_and_YNU_is_not_covered",
        },
        "controls": [
            "Do not apply YNU experimental answers unless full-log wrong=[] and fired premises certificates are correct or explicitly accepted.",
            "Keep T1_0031-style multiple-proven cases as abstain, never force-tie-break.",
            "Track every promoted rule in a stage JSON with fired/wrong/fixed/abstained counts.",
        ],
    }

def make_stage_decision(stage_reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    accepted = []
    rejected = []
    for s in stage_reports:
        rep = s.get("replay_report") or {}
        if s.get("runnable") is False:
            rejected.append({"stage": s["stage"], "reason": s.get("reason", "not runnable")})
            continue
        if rep.get("wrong") == [] and rep.get("answer_correct") == rep.get("fired"):
            accepted.append({"stage": s["stage"], "name": s["name"], "gate": "accepted_for_audit_or_safe_apply"})
        else:
            rejected.append({"stage": s["stage"], "name": s["name"], "reason": "gate_failed_or_unverified"})
    return {"accepted": accepted, "rejected_or_not_promoted": rejected}

def make_claude_handoff_text(metrics: Dict[str, Any], gap: Dict[str, Any], source_mode: str) -> str:
    all_m = metrics["groups"]["ALL"]
    mc_m = metrics["groups"]["MC"]
    ynu_m = metrics["groups"]["YNU"]
    return f"""# Claude handoff — EXACT Phase-1 v40.5 one-run audit

## Context
We are hardening an abstain-safe symbolic certificate layer for EXACT Phase-1 Type1. Current engine is an entity-grounded conjunctive Horn forward-chain solver. It should override the model only when it has a unique proof certificate.

Source mode for this run: `{source_mode}`.

## Current result summary
- All cases n: {all_m['certificate_engine_metrics']['n']}
- Fired: {all_m['certificate_engine_metrics']['fired']}
- Abstained: {all_m['certificate_engine_metrics']['abstained']}
- Fired accuracy: {all_m['certificate_engine_metrics']['fired_accuracy']}
- Strict accuracy if abstain is wrong: {all_m['certificate_engine_metrics']['strict_accuracy_abstain_as_wrong']}
- MC fired/total: {mc_m['certificate_engine_metrics']['fired']}/{mc_m['certificate_engine_metrics']['n']}
- YNU fired/total: {ynu_m['certificate_engine_metrics']['fired']}/{ynu_m['certificate_engine_metrics']['n']}

## Important verdict
Do NOT broaden by heuristic tie-break. Keep T1_0031-like `multiple` cases as abstain. Current value is precision/certificate safety, not coverage.

## Underfit / overfit
- Underfit is high because coverage is low: ALL abstains={gap['ALL']['abstained']}/{gap['ALL']['n']}, MC abstains={gap['MC']['abstained']}/{gap['MC']['n']}, YNU abstains={gap['YNU']['abstained']}/{gap['YNU']['n']}.
- Classic overfit cannot be measured from replay cases alone. Risk becomes high only if new parser rules are tuned directly to the same 25 cases without a full-log/holdout gate.

## Requested next action for Claude
Review `exact_v40_5_one_run_pipeline.py` and the stage JSON files. Improve only by adding certificate-preserving parser rules. Any candidate must output stage JSON and pass:

```python
wrong == []
answer_correct == fired
premises_used_correct does not regress
```

Never promote a YNU heuristic unless the full `exact_eval_round1_Astatine.json` verifies it. If full log is unavailable, keep YNU as audit-only.
"""

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase1", default=None, help="Path to exact_eval_round1_Astatine.json")
    ap.add_argument("--cases", default=None, help="Fallback path to v40_4_phase1_replay_cases.json")
    ap.add_argument("--out", default=None, help="Output directory")
    args = ap.parse_args(argv)

    default_root = Path("/kaggle/working") if Path("/kaggle").exists() else Path("/mnt/data")
    out = Path(args.out) if args.out else default_root / "exact_v40_5_outputs"
    out.mkdir(parents=True, exist_ok=True)

    phase1_path = find_phase1(args.phase1)
    source_mode = "phase1_log" if phase1_path else "replay_cases_only"
    input_audit = {
        "version": VERSION,
        "created_utc": now_iso(),
        "phase1_path": phase1_path,
        "source_mode": source_mode,
        "out_dir": str(out),
        "warning": None,
    }

    stage_reports: List[Dict[str, Any]] = []

    if phase1_path:
        logs = load_phase1_logs(phase1_path)
        input_audit["n_type1_logs"] = len(logs)
        # Stage 1: MC-only conservative.
        rows_mc = run_variant_on_logs(logs, "mc_only")
        rep_mc = replay_report_from_rows(rows_mc)
        stage_reports.append({"stage": 1, "name": "v40_5_mc_only_certificate", "runnable": True, "replay_report": rep_mc})
        write_json(out / "stage_01_v40_5_mc_only_cases.json", rows_mc)
        # Stage 2: YNU experimental audit, not automatic apply unless gate passes.
        rows_ynu = run_variant_on_logs(logs, "mc_plus_ynu_experimental")
        rep_ynu = replay_report_from_rows(rows_ynu)
        stage_reports.append({"stage": 2, "name": "v40_5_mc_plus_ynu_experimental_AUDIT_ONLY", "runnable": True, "replay_report": rep_ynu, "promotion_policy": "only_if_zero_wrong_and_premises_ok; otherwise reject"})
        write_json(out / "stage_02_v40_5_mc_plus_ynu_experimental_cases.json", rows_ynu)
        # Safe selected rows: currently choose MC-only unless experimental strictly dominates safely.
        selected_rows = rows_mc
        selected_name = "v40_5_mc_only_certificate"
        if rep_ynu.get("wrong") == [] and rep_ynu.get("answer_correct") == rep_ynu.get("fired") and rep_ynu.get("fired", 0) >= rep_mc.get("fired", 0):
            # Still conservative about premises: only promote if all fired premise certificates match exactly.
            if rep_ynu.get("premises_used_correct") == rep_ynu.get("fired"):
                selected_rows = rows_ynu
                selected_name = "v40_5_mc_plus_ynu_experimental_PROMOTED"
        write_json(out / "stage_03_selected_cases.json", selected_rows)
    else:
        cases_path = args.cases
        if not cases_path:
            for p in ["/mnt/data/v40_4_phase1_replay_cases.json", "./v40_4_phase1_replay_cases.json", "/kaggle/working/v40_4_phase1_replay_cases.json"]:
                if os.path.exists(p):
                    cases_path = p
                    break
        if not cases_path or not os.path.exists(cases_path):
            input_audit["warning"] = "No full phase1 log and no replay cases found. Only pipeline manifest will be written."
            rows = []
        else:
            raw_cases = json.load(open(cases_path, encoding="utf-8"))
            rows = normalize_uploaded_cases(raw_cases)
            input_audit["cases_path"] = cases_path
            input_audit["n_replay_cases"] = len(rows)
        selected_rows = rows
        selected_name = "uploaded_v40_4_replay_cases_no_full_premises"
        stage_reports.append({
            "stage": 1,
            "name": "uploaded_v40_4_replay_cases_audit",
            "runnable": bool(rows),
            "reason": None if rows else "missing_cases",
            "replay_report": replay_report_from_rows(rows) if rows else {},
        })
        stage_reports.append({
            "stage": 2,
            "name": "v40_5_full_log_upgrade_candidates",
            "runnable": False,
            "reason": "Full exact_eval_round1_Astatine.json is required to rerun parser upgrades against premises.",
        })

    # Common reports.
    current_pipeline = make_current_pipeline_json(source_mode)
    replay_report = replay_report_from_rows(selected_rows)
    metrics = full_metrics(selected_rows, source_mode)
    gap = make_gap_audit(selected_rows)
    overfit_underfit = make_overfit_underfit_audit(selected_rows, source_mode)
    decision = make_stage_decision(stage_reports)
    manifest = {
        "version": VERSION,
        "created_utc": now_iso(),
        "source_mode": source_mode,
        "selected_stage": selected_name,
        "files": {},
    }

    write_json(out / "stage_00_input_audit.json", input_audit)
    write_json(out / "stage_00_current_pipeline.json", current_pipeline)
    write_json(out / "stage_01_replay_report_selected.json", replay_report)
    write_json(out / "stage_02_full_metrics.json", metrics)
    write_json(out / "stage_03_gap_audit.json", gap)
    write_json(out / "stage_04_overfit_underfit_audit.json", overfit_underfit)
    write_json(out / "stage_05_upgrade_stage_reports.json", stage_reports)
    write_json(out / "stage_06_safe_upgrade_decision.json", decision)
    claude = make_claude_handoff_text(metrics, gap, source_mode)
    write_text(out / "CLAUDE_HANDOFF.md", claude)

    # Compact top-level summary.
    summary = {
        "version": VERSION,
        "source_mode": source_mode,
        "selected_stage": selected_name,
        "replay_report": replay_report,
        "MC_certificate_metrics": metrics["groups"]["MC"]["certificate_engine_metrics"],
        "YNU_certificate_metrics": metrics["groups"]["YNU"]["certificate_engine_metrics"],
        "ALL_after_safe_override_status_metrics": metrics["groups"]["ALL"]["after_safe_override_status_metrics"],
        "overfit_underfit_summary": overfit_underfit["summary"],
    }
    write_json(out / "SUMMARY.json", summary)

    for p in sorted(out.glob("*")):
        manifest["files"][p.name] = str(p)
    write_json(out / "MANIFEST.json", manifest)

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("\nWrote outputs to:", out)
    for p in sorted(out.glob("*")):
        print(" -", p.name)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
