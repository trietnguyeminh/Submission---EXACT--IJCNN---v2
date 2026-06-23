# -*- coding: utf-8 -*-
"""v40 entity-grounded conjunctive Horn engine for the REAL Phase-1 distribution.
Propositional over a single entity: facts = literals, rules = (conj of literals)->literal.
Forward-chain; answer options by derivability. Certificate = premise indices. Abstain-safe."""
import re
STOP={'a','an','the','of','to','in','on','at','for','and','or','that','this','their','its','it','they','them',
      'is','are','was','were','be','been','has','have','had','then','if','no','not','with','as','by','from',
      'artifact','package','manuscript','sample','batch','item','device','record','file','student'}
def _stem(t):
    if re.search(r'(ss|us|is)$',t): return t
    if re.search(r'(ches|shes|xes|zes|ses)$',t): return t[:-2]
    if re.search(r'ies$',t): return t[:-3]+'y'
    if t.endswith('s'): t=t[:-1]
    return re.sub(r'(ing|ed)$','',t)
def atom_key(phrase):
    s=re.sub(r'(?<!^)(?=[A-Z])',' ',str(phrase)).lower()
    nums=re.findall(r'\d+', s)
    toks=[ _stem(w) for w in re.findall(r'[a-zA-Z]+', s) ]
    toks=[t for t in toks if t and t not in STOP and len(t)>2]
    keys=sorted(set(toks))+["N"+n for n in sorted(set(nums))]   # keep numeric literals
    return "".join(w.capitalize() for w in keys) if keys else None

# split a clause into (atom, neg). Handles "X has Y", "X is Y", "X has no Y", "X lacks Y", "cannot ...", "is not ..."
_LEAD=re.compile(r"^\s*(if|then|that|who|which|it|its|their|this)\b",re.I)
_VERB=re.compile(r"\b(cannot|can not|can|could|may|might|must|should|shall|will|would|is not|are not|was not|were not|isn't|aren't|is|are|was|were|has no|have no|had no|has|have|had|lacks?|without|requires?|needs?|contains?|completed?|enters?|gains?|receives?|provides?|shows?|states?|holds?|carries|monitors?|captures?|eligible|allowed|approved|assigned|be|been|being)\b",re.I)
_NEGWORD=re.compile(r'\b(no|not|cannot|can not|lacks?|without|isn\'t|aren\'t|never|nor|incomplete|missing|lacking)\b',re.I)
def to_literal(clause):
    c=clause.strip().rstrip('.').strip()
    c=_LEAD.sub('',c).strip()
    neg=bool(re.search(r"\b(no|not|cannot|can not|never|lacks?|without|isn't|aren't|incomplete|missing|lacking|nor|un(?:able|verified|established))\b",c,re.I))
    m=_VERB.search(c)
    pred=c[m.end():].strip() if m else c
    # peel any leftover leading modal/aux/passive markers and articles
    for _ in range(4):
        pred=re.sub(r"^\s*(be|been|being|to|a|an|the|no|not|its|their)\b","",pred,flags=re.I).strip()
    a=atom_key(pred)
    return (a,neg) if a else None

def parse_premise(p):
    s=str(p).strip()
    m=re.search(r'^\s*if\b(.+?),?\s*\bthen\b(.+)$',s,re.I)
    if m:
        ante=re.split(r'\band\b',m.group(1),flags=re.I)
        lits=[to_literal(x) for x in ante]; lits=[l for l in lits if l]
        con=to_literal(m.group(2))
        if con and lits: return ('rule',lits,con)
        return None
    if re.search(r'^\s*(no premise|it (is|cannot)|unknown|there is no information)',s,re.I): return None
    lit=to_literal(s)
    return ('fact',lit) if lit else None

def solve_entity(premises):
    facts={}  # atom -> (bool_value, premise_idx)
    rules=[]
    for i,p in enumerate(premises):
        pp=parse_premise(p)
        if not pp: continue
        if pp[0]=='fact':
            a,neg=pp[1]; facts.setdefault(a,(not neg,[i]))
        else:
            rules.append((i,pp[1],pp[2]))
    changed=True
    while changed:
        changed=False
        for i,lits,con in rules:
            ca,cneg=con
            ok=True; path=[i]
            for a,neg in lits:
                if a in facts and facts[a][0]==(not neg): path+=facts[a][1]
                else: ok=False; break
            if ok and ca not in facts:
                facts[ca]=((not cneg),sorted(set(path))); changed=True
    return facts

_META_RE=__import__("re").compile(r"\b(not (?:yet )?(?:established|confirmed|verified|approved|cleared|determined)|cannot be (?:established|confirmed)|unsupported|is not established|no premise|undetermined|not (?:available|present))\b",__import__("re").I)
def decompose_option(opt):
    import re
    t=re.sub(r'^\s*[A-Da-d][.):]\s*','',str(opt)).strip()
    t=re.split(r'\bbecause\b',t,1,flags=re.I)[0].strip()  # drop causal justification
    parts=re.split(r',\s*but\s+|\s+but\s+|;\s+|\s+while\s+|\s+whereas\s+|\s+and\s+',t,flags=re.I)
    claims=[]
    for p in parts:
        p=p.strip()
        if not p: continue
        is_meta=bool(_META_RE.search(p))
        lit=to_literal(p)
        claims.append((lit,is_meta,p))
    return claims

def answer_mc(premises, options):
    facts=solve_entity(premises)
    res={}
    for lab,opt in zip("ABCD",options):
        claims=decompose_option(opt)
        if not claims: res[lab]=('UNSUP',[]); continue
        status='PROVEN'; path=[]
        for lit,is_meta,txt in claims:
            if lit is None: status='UNSUP'; break
            a,neg=lit; have = a in facts
            val = facts[a][0] if have else None
            if is_meta:
                # meta "not established": correct only if NOT positively proven
                if have and val==True: status='DISPROVEN'; break
            else:
                if have and val==(not neg): path+=facts[a][1]
                elif have and val==(neg): status='DISPROVEN'; break
                else: status='UNSUP'; break
        res[lab]=(status, sorted(set(path)))
    proven=[l for l in res if res[l][0]=='PROVEN']
    if len(proven)==1: return proven[0],res[proven[0]][1],'entity_unique_proof',res
    return None,[],('multiple' if proven else 'none'),res


# ================= Phase-1 REPLAY HARNESS =================
def _opt_texts(rp):
    import re
    f=[o[1].strip().replace("\n"," ") for o in re.findall(r"(?:^|\n)\s*([A-D])[.)]\s*(.+?)(?=\n\s*[A-D][.)]|\Z)",rp.get("query",""),flags=re.S)]
    return f if len(f)>=2 else (rp.get("options") or [])
def replay_phase1(path):
    import json,re
    d=json.load(open(path)); t1=[l for l in d["logs"] if l.get("type")=="type1"]
    fired=aok=pok=0; fixed=[]; wrong=[]; abst=0
    for l in t1:
        rp=l["request_payload"]; exp=l.get("expected") or {}; ea=str(exp.get("answer","")).strip().upper()
        opts=_opt_texts(rp)
        if not opts: continue
        a,pu,why,res=answer_mc(rp.get("premises",[]) or [], opts)
        if a is None: abst+=1; continue
        fired+=1; ok=(a==ea); aok+=ok; pok+=(sorted(pu)==sorted(exp.get("premises_used") or []))
        if ok and l.get("status")!="correct": fixed.append(l["query_id"])
        if not ok: wrong.append({"query_id":l["query_id"],"exp":ea,"got":a})
    rep={"n":len(t1),"fired":fired,"answer_correct":aok,"premises_used_correct":pok,
         "wrong":wrong,"fixed_old_wrong":fixed,"abstained":abst,
         "precision_when_fired":round(aok/max(fired,1),3),"coverage":round(fired/max(len(t1),1),3),
         "gate":"ABSTAIN_SAFE" if not wrong else "HAS_WRONG_FIX_BEFORE_APPLY"}
    return rep
def _autofind():
    import glob,os,sys
    if len(sys.argv)>1 and os.path.exists(sys.argv[1]): return sys.argv[1]
    for c in ["exact_eval_round1_Astatine.json","/kaggle/input/**/exact_eval_round1_Astatine.json",
              "/kaggle/working/exact_eval_round1_Astatine.json","./exact_eval_round1_Astatine.json"]:
        h=sorted(glob.glob(c,recursive=True)) if any(x in c for x in "*?[") else ([c] if os.path.exists(c) else [])
        if h: return h[0]
    return None
if __name__=="__main__":
    import json
    p=_autofind()
    if not p: print("exact_eval_round1_Astatine.json not found; pass path as arg."); raise SystemExit(1)
    rep=replay_phase1(p); json.dump(rep,open("v40_phase1_replay_report.json","w"),indent=1)
    print(json.dumps(rep,indent=1))
