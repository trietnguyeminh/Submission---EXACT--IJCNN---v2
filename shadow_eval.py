# -*- coding: utf-8 -*-
"""Strictly-additive SHADOW evaluator for Type1 symbolic candidates.
Compares a candidate engine against the FROZEN baseline on the Phase-1 regression harness.
Golden rule: PROMOTE only if added!=[] AND lost==[] AND changed_premises==[] AND wrong==[]
             AND no new multiple-proven. Otherwise REJECT (or ACCEPT_SHADOW if harmless-no-gain).
Emits: candidate_diff_report.json, abstain_taxonomy.json, proof_certificate_cases.json,
       safe_upgrade_decision.json
"""
import json,re,sys,os

def load_engine(path):
    src=open(path).read()
    src=src.split("# ================= Phase-1 REPLAY")[0] if "# ================= Phase-1 REPLAY" in src else src.split("if __name__")[0]
    g={}; exec(src,g); return g

def opt_texts(rp):
    q=rp.get("query","")
    f=[o[1].strip().replace("\n"," ") for o in re.findall(r"(?:^|\n)\s*([A-D])[.)]\s*(.+?)(?=\n\s*[A-D][.)]|\Z)",q,flags=re.S)]
    return f if len(f)>=2 else []

def run_engine(g, t1):
    out={}
    for l in t1:
        rp=l["request_payload"]; opts=opt_texts(rp)
        if not opts: out[l["query_id"]]={"answer":None,"premises_used":[],"why":"no_options","res":{}}; continue
        a,pu,why,res=g["answer_mc"](rp.get("premises",[]) or [], opts)
        out[l["query_id"]]={"answer":a,"premises_used":sorted(pu),"why":why,
                            "res":{k:res[k][0] for k in res}}
    return out

def taxonomy(g, l, r):
    if r["answer"] is not None: return "FIRED"
    if r["why"]=="multiple": return "multiple_direct_proven"
    prems=l["request_payload"].get("premises",[]) or []
    facts=rules=0
    for p in prems:
        pp=g["parse_premise"](p)
        if not pp: continue
        facts+=(pp[0]=="fact"); rules+=(pp[0]=="rule")
    if facts==0 and rules==0: return "entity_conjunction_parse_miss"
    opts=opt_texts(l["request_payload"])
    if not opts: return "ynu_unsupported"
    if any(re.search(r",?\s*(but|and|;|while|whereas|because)\s+",o,re.I) for o in opts): return "compound_option_unparsed"
    return "predicate_mismatch"

def evaluate(baseline_path, candidate_path, phase1_path, outdir):
    os.makedirs(outdir,exist_ok=True)
    d=json.load(open(phase1_path)); t1=[l for l in d["logs"] if l.get("type")=="type1"]
    exp={l["query_id"]:(l.get("expected") or {}) for l in t1}
    gold={q:str(e.get("answer","")).strip() for q,e in exp.items()}
    gB=load_engine(baseline_path); B=run_engine(gB,t1)
    gC=load_engine(candidate_path); C=run_engine(gC,t1)
    base_fired={q for q,r in B.items() if r["answer"] is not None}
    cand_fired={q for q,r in C.items() if r["answer"] is not None}
    def correct(q,r):
        g=gold[q].upper(); a=str(r["answer"]).strip()
        return a.upper()==g if g in {"A","B","C","D"} else a.lower()==g.lower()
    added=sorted(cand_fired-base_fired)
    lost=sorted(base_fired-cand_fired)
    # premises_used changed on cases fired in BOTH
    changed_premises=[q for q in (base_fired & cand_fired) if B[q]["premises_used"]!=C[q]["premises_used"]]
    wrong=sorted([q for q in cand_fired if not correct(q,C[q])])
    new_multi=[q for q,r in C.items() if r["why"]=="multiple" and B[q]["why"]!="multiple"]
    # decision
    if wrong or lost or changed_premises or new_multi:
        decision="REJECT"
    elif added:
        decision="PROMOTE"   # strictly additive + gains
    else:
        decision="ACCEPT_SHADOW_ONLY"  # harmless, no gain
    diff={"candidate":os.path.basename(candidate_path),"baseline":os.path.basename(baseline_path),
          "n":len(t1),"baseline_fired_set":sorted(base_fired),"candidate_fired_set":sorted(cand_fired),
          "added":added,"lost":lost,"changed_premises":changed_premises,
          "candidate_wrong":wrong,"new_multiple_proven":new_multi,"decision":decision,
          "reject_reasons":[r for r,ok in [("has_wrong",bool(wrong)),("lost_cases",bool(lost)),
                            ("changed_premises",bool(changed_premises)),("new_multiple_proven",bool(new_multi))] if ok]}
    json.dump(diff,open(os.path.join(outdir,"candidate_diff_report.json"),"w"),indent=1)
    # abstain taxonomy (baseline)
    from collections import Counter; tax=Counter(); rows=[]
    for l in t1:
        t=taxonomy(gB,l,B[l["query_id"]]); tax[t]+=1
        rows.append({"query_id":l["query_id"],"taxonomy":t,"gold":gold[l["query_id"]],"old_status":l.get("status")})
    json.dump({"taxonomy":dict(tax),"cases":rows},open(os.path.join(outdir,"abstain_taxonomy.json"),"w"),indent=1)
    # proof certificate cases (baseline fired)
    certs=[{"query_id":q,"answer":B[q]["answer"],"premises_used":B[q]["premises_used"],"rule":B[q]["why"],
            "premises_used_matches_gold":(B[q]["premises_used"]==sorted(exp[q].get("premises_used") or []))}
           for q in sorted(base_fired)]
    json.dump({"baseline":os.path.basename(baseline_path),"fired":len(certs),"cases":certs},
              open(os.path.join(outdir,"proof_certificate_cases.json"),"w"),indent=1)
    # safe upgrade decision
    json.dump({"decision":decision,"diff":diff,"golden_rule":"PROMOTE iff added!=[] and lost==[] and changed_premises==[] and wrong==[] and no new multiple-proven"},
              open(os.path.join(outdir,"safe_upgrade_decision.json"),"w"),indent=1)
    return diff

if __name__=="__main__":
    base=sys.argv[1] if len(sys.argv)>1 else "v40_4_entity_conjunctive_engine.py"
    cand=sys.argv[2] if len(sys.argv)>2 else base
    p1=sys.argv[3] if len(sys.argv)>3 else "exact_eval_round1_Astatine.json"
    out=sys.argv[4] if len(sys.argv)>4 else "shadow_outputs"
    diff=evaluate(base,cand,p1,out)
    print(json.dumps(diff,indent=1))
