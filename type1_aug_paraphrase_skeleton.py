# -*- coding: utf-8 -*-
"""type1_aug_paraphrase_skeleton.py (hardened) — anti-circular Type1 parser stress augmenter.
Each sample carries an ABSTRACT skeleton (atoms P1/P2/.., rules, option->abstract-claim).
Validator = abstract reference solver (independent of v40): guarantees correct-unique,
distractors-not-provable, canary->>=2 proven. v40 is SYSTEM-UNDER-TEST on paraphrased surface.
Use for parser stress-test + shadow-eval ONLY. Not for LoRA training; not sole promotion evidence.
"""
import json,random,re,sys,os
random.seed(11)

TOPICS=[
 {"ent":"MedKit-7","P1":["launch clearance","clearance for launch"],"P2":["a blocked-route report","a route-blocking flag"],"P3":["eligible to use the aerial corridor","permitted on the aerial corridor"]},
 {"ent":"The River Codex","P1":["a 600 dpi scan","a high-resolution scan"],"P2":["a privacy flag","an unresolved privacy issue"],"P3":["eligible for the public portal","portal-eligible"]},
 {"ent":"Satellite Vega","P1":["calibrated thermal sensors","thermal sensors that are calibrated"],"P2":["a radar fault","a sensor fault"],"P3":["able to support disaster mapping","disaster-mapping capable"]},
 {"ent":"Batch Nova","P1":["an intact seal","a seal that is intact"],"P2":["a temperature breach","a cold-chain breach"],"P3":["release-ready","ready for release"]},
]
def _np(ph): return re.sub(r'^(a|an)\s+','',ph)
def say_pos(e,ph): return random.choice([f"{e} has {ph}.",f"{_np(ph).capitalize()} is present for {e}.",f"{e} carries {ph}."])
def say_neg(e,ph): p=_np(ph); return random.choice([f"{e} has no {p}.",f"No {p} is recorded for {e}.",f"{e} lacks {p}."])
def say_state(e,ph): return random.choice([f"{e} is {ph}.",f"{e} becomes {ph}.",f"{_np(ph).capitalize()} applies to {e}."])
def rule_para(a,b,c):  # surface variety of: has A and no B -> C  (STRESS the parser)
    bp=_np(b)
    return random.choice([
      f"If an item has {a} and no {bp}, then it is {c}.",
      f"When an item has {a} but no {bp}, it is {c}.",
      f"Any item with {a} and without {bp} is {c}.",
      f"An item that has {a} and lacks {bp} is {c}."])

# ---- abstract reference solver (independent of v40) ----
def abstract_solve(spec):
    facts=dict(spec["facts"])  # atom->bool
    for _ in range(8):
        ch=False
        for (ante,con) in spec["rules"]:
            if all(facts.get(a)==v for a,v in ante) and con[0] not in facts:
                facts[con[0]]=con[1]; ch=True
        if not ch: break
    return facts
def claim_status(claim, facts):
    a,v=claim
    if a in facts: return "PROVEN" if facts[a]==v else "DISPROVEN"
    return "UNSUP"

def gen_conjunctive(canary=False):
    t=random.choice(TOPICS); e=t["ent"]; a=random.choice(t["P1"]); b=random.choice(t["P2"]); c=random.choice(t["P3"])
    prem=[rule_para(a,b,c), say_pos(e,a), say_neg(e,b)]
    spec={"facts":{"P1":True,"P2":False},"rules":[([("P1",True),("P2",False)],("P3",True))],
          "options":{}}
    # options + abstract claims
    optmap={"A":(f"{e} has {_np(b)}",("P2",True)),    # FALSE (P2 is false)
            "B":(f"{e} has an audit waiver",("WAIV",True)),  # unsupported
            "C":(f"{e} is {c}",("P3",True)),           # correct
            "D":(f"{e} is not {c}",("P3",False))}      # contradiction
    if canary:
        # make B genuinely also-proven: add fact P1 claim as option B (P1 true) + add a second true fact
        optmap["B"]=(f"{e} has {a}",("P1",True))
    opts=[f"{lab}. {txt}" for lab,(txt,_) in optmap.items()]
    spec["options"]={lab:cl for lab,(_,cl) in optmap.items()}
    ans=None if canary else "C"; pu=[] if canary else [0,1,2]
    return {"logic_family":"entity_conjunctive_mc","surface_family":f"para_{e.split()[-1].lower()}",
            "entity":e,"premises":prem,"query":"Based on the premises, which statement is correct?\n"+"\n".join(opts),
            "options":opts,"answer":ans,"premises_used":pu,"canary":canary,"abstract":spec}

def gen_meta_unknown():
    t=random.choice(TOPICS); e=t["ent"]; a=random.choice(t["P1"]); x=random.choice(["budget approval","export license"])
    prem=[say_pos(e,a), f"No premise states whether {e} has {x}."]
    # YNU-style but presented as MC with Uncertain option
    optmap={"A":(f"{e} has {x}",("X",True)),"B":(f"{e} has no {x}",("X",False)),
            "C":(f"It cannot be determined whether {e} has {x}",("META",True)),"D":(f"{e} has {a}",("P1",True))}
    spec={"facts":{"P1":True},"rules":[],"options":{lab:cl for lab,(_,cl) in optmap.items()}}
    opts=[f"{lab}. {txt}" for lab,(txt,_) in optmap.items()]
    # correct = C (meta) since X undetermined; but D(P1) is also true -> ambiguous! so gold=D? keep simple: drop D-as-true
    optmap["D"]=(f"{e} lacks {a}",("P1",False)); opts[3]=f"D. {e} lacks {_np(a)}"
    spec["options"]["D"]=("P1",False)
    return {"logic_family":"meta_unknown","surface_family":"meta","entity":e,
            "premises":prem,"query":"Which statement is correct?\n"+"\n".join(opts),
            "options":opts,"answer":"C","premises_used":[1],"canary":False,"abstract":spec,"meta_option":"C"}

GENS=[("conjunctive",lambda:gen_conjunctive(False)),("canary",lambda:gen_conjunctive(True)),("meta",gen_meta_unknown)]

def make(n,split):
    out=[]
    for i in range(n):
        nm,gn=random.choice(GENS); s=gn(); s["sample_id"]=f"{split}_{i:04d}"; s["split"]=split; out.append(s)
    return out

# ---- HARDENED validator: abstract reference solver, reject ill-formed ----
def validate(rows):
    rep={"total":len(rows),"rejected":0,"reasons":{}}; keep=[]
    for s in rows:
        facts=abstract_solve(s["abstract"]); opts=s["abstract"]["options"]
        # meta option: treated as PROVEN iff no other DIRECT option proven
        direct_proven=[l for l,cl in opts.items() if cl[0]!="META" and claim_status(cl,facts)=="PROVEN"]
        proven=set(direct_proven)
        if s.get("meta_option") and not direct_proven: proven.add(s["meta_option"])
        bad=None
        if s["canary"]:
            if len(proven)<2: bad="canary_not_multi_proven"
        else:
            if len(proven)!=1: bad="not_unique_proven"
            elif list(proven)[0]!=s["answer"]: bad="proven_mismatch_gold"
            elif not s["premises_used"]: bad="empty_premises_used"
        if bad: rep["rejected"]+=1; rep["reasons"][bad]=rep["reasons"].get(bad,0)+1
        else: keep.append(s)
    return keep,rep

# ---- parser stress: v40 on surface vs abstract-validated gold ----
def stress(rows, engine):
    src=open(engine).read().split("if __name__")[0]; g={}; exec(src,g); am=g["answer_mc"]
    fired=ok=puok=wrong=can_ok=can_n=0; groups={}
    for s in rows:
        a,pu,why,res=am(s["premises"],s["options"])
        if s["canary"]:
            can_n+=1; can_ok+=(a is None); continue
        if a is None: continue
        fired+=1; c=(str(a).upper()==str(s["answer"]).upper()); ok+=c; puok+=(sorted(pu)==sorted(s["premises_used"])); wrong+=(not c)
        groups.setdefault(s["surface_family"],set()).add(a)
    cons=[len(v)==1 for v in groups.values() if len(v)>1]
    return {"n":len(rows),"fired":fired,"correct_when_fired":ok,"premises_used_correct":puok,
            "wrong_real_parser":wrong,"canary_n":can_n,"canary_abstained":can_ok,
            "paraphrase_consistency":f"{sum(cons)}/{len(cons)}" if cons else "n/a"}

if __name__=="__main__":
    ENG=sys.argv[1]; OUT=sys.argv[2]; DEV=int(sys.argv[3]) if len(sys.argv)>3 else 80; HOLD=int(sys.argv[4]) if len(sys.argv)>4 else 200
    os.makedirs(OUT,exist_ok=True)
    dev,vd=validate(make(DEV,"dev")); hold,vh=validate(make(HOLD,"holdout"))
    json.dump(dev,open(f"{OUT}/type1_aug_dev.json","w"),indent=1); json.dump(hold,open(f"{OUT}/type1_aug_holdout.json","w"),indent=1)
    json.dump({"dev":vd,"holdout":vh},open(f"{OUT}/type1_aug_validator_report.json","w"),indent=1)
    st={"dev":stress(dev,ENG),"holdout":stress(hold,ENG)}
    json.dump(st,open(f"{OUT}/type1_aug_parser_stress_report.json","w"),indent=1)
    json.dump({"purpose":"parser stress-test + shadow-eval ONLY","anti_circular":"abstract reference solver validates samples; v40 only tested on surface","validator":"reject if not unique-proven / canary<2 / distractor provable"},open(f"{OUT}/type1_aug_manifest.json","w"),indent=1)
    print("validator:",json.dumps({"dev":vd,"holdout":vh}))
    print("stress:",json.dumps(st,indent=1))
