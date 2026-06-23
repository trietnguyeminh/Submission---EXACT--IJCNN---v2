# live_v38b_v39_wrapper.py — self-contained symbolic pre-handler (no deps, no LLM).

# v38b engine (unchanged)
# CELL 1 — v39 canonical predicate
import re
# ---------- v39-lite: canonical predicate ----------
def canon_atom(s):
    s=str(s).strip()
    s=re.sub(r'\(x\)|\(\s*x\s*\)','',s)
    s=s.strip()
    # FOL CamelCase atom -> as-is canonical key
    if re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', s):
        return s
    # NL fallback: tokenize, drop stopwords/subjects, light de-inflect, join
    STOP={'a','an','the','of','to','in','on','at','for','and','or','that','this','their','his','her','its',
          'all','every','each','some','any','there','is','are','do','does','did','student','students','researcher',
          'researchers','who','which','it','they','them','then','if','not'}
    toks=re.findall(r"[a-zA-Z]+", s.lower())
    out=[]
    for t in toks:
        if t in STOP: continue
        t=re.sub(r'(ies)$','y',t); t=re.sub(r'(es|s)$','',t); t=re.sub(r'(ing|ed)$','',t)
        out.append(t)
    return "_".join(out) if out else s.lower()

def _norm_tokens(text):
    text=re.sub(r'(?<!^)(?=[A-Z])',' ',str(text))
    toks=re.findall(r'[a-zA-Z]+', text.lower())
    STOP={'a','an','the','of','to','in','on','at','for','and','or','that','this','their','his','her','its',
          'all','every','each','some','any','there','is','are','do','does','did','student','students','researcher',
          'researchers','who','which','it','they','them','then','if','not','one','least','according','premise',
          'premises','following','statement','true','based','above','can','be','inferred','supported','logically'}
    def _stem(t):
        if re.search(r'(ss|us|is)$', t): pass
        elif re.search(r'(ches|shes|xes|zes|ses)$', t): t=t[:-2]
        elif re.search(r'ies$', t): t=t[:-3]+'y'
        elif t.endswith('s'): t=t[:-1]
        t=re.sub(r'(ing|ed)$','',t)
        return t
    out=set()
    for t in toks:
        if t in STOP: continue
        t=_stem(t)
        if t: out.add(t)
    return out

# CELL 2 — FOL parser
# ---------- FOL parser ----------
def parse_fol(fol):
    """Return ('rule',A,B) | ('uni',A) | ('uni_neg',A) | ('exist',A) | ('exist_neg',A) | None"""
    f=str(fol).replace('->','→').replace('¬','~').replace('∀','A').replace('∃','E')
    f=f.strip()
    # implication
    m=re.search(r'\(?\s*([~]?\s*[A-Za-z0-9]+)\s*\(x\)\s*→\s*([~]?\s*[A-Za-z0-9]+)\s*\(x\)\s*\)?', f)
    if m and f.startswith('A'):
        a=m.group(1).replace(' ',''); b=m.group(2).replace(' ','')
        an=a.startswith('~'); bn=b.startswith('~')
        return ('rule', (canon_atom(a.lstrip('~')),an), (canon_atom(b.lstrip('~')),bn))
    # quantified single atom
    m=re.search(r'^([AE])\s*x?\s*\(?\s*(~?)\s*([A-Za-z0-9]+)\s*\(x\)\s*\)?$', f)
    if m:
        quant,neg,pred=m.group(1),m.group(2)=='~',canon_atom(m.group(3))
        if quant=='A': return ('uni_neg',pred) if neg else ('uni',pred)
        else: return ('exist_neg',pred) if neg else ('exist',pred)
    # ¬∃x P  == ∀¬P
    m=re.search(r'~\s*E\s*x?\s*\(?\s*([A-Za-z0-9]+)\s*\(x\)', f)
    if m: return ('uni_neg',canon_atom(m.group(1)))
    return None

# CELL 3 — Closure
# ---------- closure ----------
def build_closure(premises_fol):
    rules=[]; uni=set(); uni_neg=set(); exist=set()
    prov={}  # atom -> premise idx that introduced it (for path)
    for i,fol in enumerate(premises_fol):
        p=parse_fol(fol)
        if not p: continue
        if p[0]=='rule': rules.append((i,p[1],p[2]))
        elif p[0]=='uni': uni.add(p[1]); prov.setdefault(('pos',p[1]),[i])
        elif p[0]=='uni_neg': uni_neg.add(p[1]); prov.setdefault(('neg',p[1]),[i])
        elif p[0]=='exist': exist.add(p[1]); prov.setdefault(('ex',p[1]),[i])
    # forward positive: uni + (A->B, A pos, B pos-polarity) => B uni
    changed=True
    while changed:
        changed=False
        for i,(a,an),(b,bn) in rules:
            # positive modus ponens: rule with both positive
            if not an and not bn and a in uni and b not in uni:
                uni.add(b); prov[('pos',b)]=prov.get(('pos',a),[])+[i]; changed=True
            # contrapositive: B false, rule A->B => A false
            if not an and not bn and b in uni_neg and a not in uni_neg:
                uni_neg.add(a); prov[('neg',a)]=prov.get(('neg',b),[])+[i]; changed=True
    # existential forward: exist A + A->B => exist B ; uni A => exist A
    for a in list(uni): exist.add(a); prov.setdefault(('ex',a),prov.get(('pos',a),[]))
    changed=True
    while changed:
        changed=False
        for i,(a,an),(b,bn) in rules:
            if not an and not bn and a in exist and b not in exist:
                exist.add(b); prov[('ex',b)]=prov.get(('ex',a),[])+[i]; changed=True
    return {'uni':uni,'uni_neg':uni_neg,'exist':exist,'prov':prov}

# CELL 4 — Query type + target matching
# ---------- query type + target ----------
def query_type(q):
    ql=str(q).lower()
    if re.search(r'\bat least one\b|\bsome\b|\bany\b|\bthere (is|exists)\b|does .* one', ql): return 'existential'
    if re.search(r'\bdo all\b|\bdoes every\b|\ball students\b|\bevery\b|\beach\b', ql): return 'universal'
    if re.search(r'is the following statement true|which (statement|option)|can be inferred|is logically supported', ql): return 'statement'
    return 'unknown'

def target_atom(q, atoms):
    qt=_norm_tokens(q)
    scored=[]
    for a in atoms:
        at=_norm_tokens(a)
        if not at: continue
        ov=len(qt & at)/len(at)   # fraction of atom tokens covered by question
        scored.append((ov,len(at & qt),a))
    scored.sort(reverse=True)
    if not scored: return None
    top=scored[0]
    if top[0] < 0.6 or top[1] < 1: return None
    # uniqueness: if a different atom ties on coverage AND raw overlap, ambiguous
    ties=[s for s in scored if abs(s[0]-top[0])<1e-9 and s[1]==top[1] and s[2]!=top[2]]
    if ties: return None
    return top[2]

# CELL 5 — YNU projection + certificate (UNCHANGED from v38)
# ---------- projection with v35 convention + certificate ----------
def prove(premises_fol, question):
    cl=build_closure(premises_fol)
    atoms=cl['uni']|cl['uni_neg']|cl['exist']|{a for _,(a,_),(b,_) in [] }
    allatoms=set()
    for fol in premises_fol:
        p=parse_fol(fol)
        if not p: continue
        if p[0]=='rule': allatoms.add(p[1][0]); allatoms.add(p[2][0])
        else: allatoms.add(p[1])
    qt=query_type(question); tgt=target_atom(question, allatoms)
    cert={'query_type':qt,'target':tgt,'positive':None,'negative':None,'answer':None,'premises_used':[],'abstain_reason':None}
    if tgt is None:
        cert['answer']=None; cert['abstain_reason']='target_not_matched'; return cert
    pos = tgt in cl['uni'] or tgt in cl['exist']
    neg = tgt in cl['uni_neg']
    cert['positive']=pos; cert['negative']=neg
    if qt=='existential':
        if neg:  # E1: forall-not target -> no instance (convention: wins even under positive conflict)
            cert['answer']='No'; cert['premises_used']=cl['prov'].get(('neg',tgt),[]); cert['proof_rule']='E1_universal_negative'
        elif pos:
            cert['answer']='Yes'; cert['premises_used']=cl['prov'].get(('ex',tgt),cl['prov'].get(('pos',tgt),[])); cert['proof_rule']='PE_witness'
        else:
            cert['answer']=None; cert['abstain_reason']='no_proof'
    elif qt=='universal':
        if tgt in cl['uni']:  # PY: positive universal wins
            cert['answer']='Yes'; cert['premises_used']=cl['prov'].get(('pos',tgt),[]); cert['proof_rule']='PY_universal_positive'
        elif neg:
            cert['answer']='No'; cert['premises_used']=cl['prov'].get(('neg',tgt),[]); cert['proof_rule']='U1_universal_negative'
        else:
            cert['answer']=None; cert['abstain_reason']='no_proof'
    else:
        cert['answer']=None; cert['abstain_reason']='statement_or_mc_out_of_scope'
    cert['premises_used']=sorted(set(cert['premises_used']))
    return cert

# CELL 6 — v38b MC: option-type classifier + conditional-distractor exclusion + meta policy
def classify_option(opt):
    t=re.sub(r"^\s*[A-Da-d][.):]\s*","",str(opt).strip())  # strip "A." / "B)" prefix if present
    tl=t.lower()
    if re.search(r"cannot be (determined|inferred)|undetermined|does not (support|allow)|no conclusion|insufficient", tl):
        return "META"
    # conditional / relative-clause distractor: "X who/that ... must/will/should ..." or "if ... then ..."
    if re.search(r"\bwho\b|\bthat\b", tl) and re.search(r"\b(must|will|should|then)\b", tl): return "CONDITIONAL"
    if re.search(r"^\s*if\b", tl): return "CONDITIONAL"
    if re.search(r"\bmust\b", tl): return "CONDITIONAL"   # malformed "must completes"
    if re.search(r"^\s*no\b", tl): return "UNIV_NEG"
    if re.search(r"^\s*(only some|some only)\b", tl): return "PARTIAL"
    if re.search(r"^\s*(at least one|some|there (is|exists))\b", tl): return "EXIST_POS"
    if re.search(r"^\s*(every|all|each)\b", tl): return "UNIV_POS"
    return "UNKNOWN_OPT"

def allatoms_of(fol):
    A=set()
    for f in fol:
        p=parse_fol(f)
        if not p: continue
        if p[0]=="rule": A.add(p[1][0]); A.add(p[2][0])
        else: A.add(p[1])
    return A

def eval_direct(kind, opt, cl, allatoms):
    atom=target_atom(opt, allatoms)
    if atom is None: return "UNSUPPORTED",None
    if kind=="UNIV_POS": return ("PROVEN" if atom in cl['uni'] else ("DISPROVEN" if atom in cl['uni_neg'] else "UNSUPPORTED")),atom
    if kind=="UNIV_NEG": return ("PROVEN" if atom in cl['uni_neg'] else ("DISPROVEN" if atom in cl['uni'] else "UNSUPPORTED")),atom
    if kind=="EXIST_POS": return ("PROVEN" if atom in cl['exist'] else ("DISPROVEN" if atom in cl['uni_neg'] else "UNSUPPORTED")),atom
    if kind=="PARTIAL":
        if atom in cl['exist'] and atom not in cl['uni'] and atom not in cl['uni_neg']: return "PROVEN",atom
        return ("DISPROVEN" if (atom in cl['uni'] or atom in cl['uni_neg']) else "UNSUPPORTED"),atom
    return "UNSUPPORTED",atom

def prove_mc_v38b(fol, options):
    cl=build_closure(fol); allatoms=allatoms_of(fol)
    labels=list("ABCD")[:len(options)]
    proven=[]; meta=None; prov_atom=None
    for lab,opt in zip(labels,options):
        k=classify_option(opt)
        if k=="META": meta=lab; continue
        if k in ("CONDITIONAL","UNKNOWN_OPT"): continue   # never selectable
        st,atom=eval_direct(k,opt,cl,allatoms)
        if st=="PROVEN": proven.append((lab,atom))
    cert={'answer':None,'rule':None,'premises_used':[],'abstain_reason':None}
    if len(proven)==1:
        lab,atom=proven[0]; cert['answer']=lab; cert['rule']='MC_unique_direct_proof'
        for key in [('pos',atom),('neg',atom),('ex',atom)]:
            if key in cl['prov']: cert['premises_used']=sorted(set(cl['prov'][key])); break
    elif len(proven)==0 and meta is not None:
        cert['answer']=meta; cert['rule']='MC_meta_cannot_determine'
    else:
        cert['abstain_reason']=('multiple_direct_proven' if proven else 'no_direct_and_no_meta')
    return cert
print('v38b MC policy ready')

# v39 parser
# -*- coding: utf-8 -*-
"""v39 NL->predicate parser: NL premises -> canonical FOL atoms, so the v38b engine
runs in live (NL-only) setting. Atom key = CamelCase of sorted normalized content tokens,
so NL phrases and the FOL oracle map to the SAME atom namespace -> directly comparable."""
import re
STOP={'a','an','the','of','to','in','on','at','for','and','or','that','this','their','his','her','its',
      'all','every','each','some','any','there','is','are','do','does','did','student','students','researcher',
      'researchers','intern','interns','developer','developers','employee','employees','candidate','candidates',
      'member','members','person','people','who','which','it','they','them','then','if','one','least','must',
      'will','should'}  # domain nouns kept (course/exam carry meaning) intentionally

def _stem(t):
    if re.search(r'(ss|us|is)$',t): return t
    if re.search(r'(ches|shes|xes|zes|ses)$',t): return t[:-2]
    if re.search(r'ies$',t): return t[:-3]+'y'
    if t.endswith('s'): t=t[:-1]
    return re.sub(r'(ing|ed)$','',t)
def _toks(text):
    text=re.sub(r'(?<!^)(?=[A-Z])',' ',str(text))
    out=[]
    for w in re.findall(r'[a-zA-Z]+',text.lower()):
        if w in STOP: continue
        s=_stem(w)
        if s: out.append(s)
    return out
def atom_key(phrase):
    t=sorted(set(_toks(phrase)))
    return "".join(w.capitalize() for w in t) if t else None

NEG=re.compile(r'\b(no|not|never|cannot|can\'t|does not|do not|doesn\'t|don\'t|fails? to|unable)\b',re.I)
def _polarity(s): return bool(NEG.search(s))

def nl_premise_to_fol(nl):
    s=str(nl).strip()
    m=re.search(r'^\s*if\b(.+?),?\s*\bthen\b(.+)$',s,re.I)
    if m:
        a,b=m.group(1),m.group(2)
        ak,bk=atom_key(a),atom_key(b)
        if not ak or not bk: return None
        an='¬' if _polarity(a) else ''; bn='¬' if _polarity(b) else ''
        return f'∀x ({an}{ak}(x) → {bn}{bk}(x))'
    m=re.search(r'^\s*(every|all|each)\b(.+)$',s,re.I)
    if m:
        body=m.group(2); k=atom_key(body)
        if not k: return None
        return f'∀x ({"¬" if _polarity(body) else ""}{k}(x))'
    m=re.search(r'^\s*no\b(.+)$',s,re.I)
    if m:
        k=atom_key(m.group(1));  return f'∀x (¬{k}(x))' if k else None
    m=re.search(r'^\s*(at least one|some|there (?:is|exists)|at least)\b(.+)$',s,re.I)
    if m:
        body=m.group(2); k=atom_key(body)
        if not k: return None
        return f'∃x ({"¬" if _polarity(body) else ""}{k}(x))'
    return None

def nl_to_canon(premises_nl):
    return [nl_premise_to_fol(p) for p in premises_nl]

def fol_to_canon(premises_fol):
    """Re-emit oracle FOL into the SAME atom namespace (CamelCase of sorted tokens)."""
    out=[]
    for f in premises_fol:
        s=str(f)
        def rep(m):
            neg=m.group(1) or ''
            k=atom_key(m.group(2))
            return f'{neg}{k}(x)'
        s2=re.sub(r'(¬?)\s*([A-Za-z][A-Za-z0-9]*)\(x\)',rep,s)
        out.append(s2)
    return out

# LIVE wrapper: run v38b certificate engine on NL-only premises (no FOL available)
import re
def parse_opts(q): return [o[1].strip().replace("\n"," ") for o in re.findall(r"(?:^|\n)\s*([A-D])[.)]\s*(.+?)(?=\n\s*[A-D][.)]|\Z)", q, flags=re.S)]
def _is_ynu_options(options):
    vals={str(o).strip().lower() for o in (options or [])}; vals={v for v in vals if v}
    return bool(vals) and vals <= {"yes","no","unknown","uncertain"}

def verify_v38_live(question, premises_nl, options=None):
    """NL premises -> canonical FOL -> v38b proof. Returns (answer|None, premises_used, rule), cert."""
    canon=nl_to_canon(premises_nl)
    if not any(canon):
        return (None,[],"nl_parse_empty"), {"answer":None,"abstain_reason":"nl_parse_empty","canon_premises":canon}
    opts=options or parse_opts(question)
    # MC when options are real answer choices (not Yes/No/Uncertain)
    if opts and not _is_ynu_options(opts):
        c=prove_mc_v38b(canon, opts)
        c["canon_premises"]=canon
        return (c.get("answer"), c.get("premises_used",[]), c.get("rule") or c.get("abstain_reason")), c
    c=prove(canon, question)
    c["canon_premises"]=canon
    return (c.get("answer"), c.get("premises_used",[]), c.get("proof_rule") or c.get("abstain_reason")), c

print("verify_v38_live ready (NL-only)")

# ================= UNIT TESTS (run: python live_v38b_v39_wrapper.py) =================
MC_OPTS=["A. Every student completes the coursework.",
         "B. It cannot be determined whether every student completes the coursework.",
         "C. No student completes the coursework.",
         "D. Every student who earns course credit must completes."]
MC_Q="Which statement is correct?\n"+"\n".join(MC_OPTS)

def _run_unit_tests():
    res=[]
    def t(name, q, premises, options, exp, exp_prem=None):
        (a,pu,why),_=verify_v38_live(q, premises, options)
        ok=(a==exp) and (exp_prem is None or sorted(pu)==sorted(exp_prem))
        res.append((ok,name,exp,a,why,pu))
    chain=["Every researcher reads the literature.",
           "If a researcher reads the literature, then the researcher identifies a gap.",
           "If a researcher identifies a gap, then the researcher designs a study."]
    t("YNU positive chain -> Yes",     "Do all researchers design a study?", chain, None, "Yes", [0,1,2])
    eneg=["Every researcher improves technique.",
          "If a researcher improves technique, then the researcher scores above threshold.",
          "No researcher scores above threshold."]
    t("YNU existential-negative -> No","Does at least one researcher improve technique?", eneg, None, "No")
    t("Unknown / no proof -> abstain", "Do all students submit all assignments?",
      ["If a student submits all assignments, then the student achieves a high GPA.","Every student achieves a high GPA."], None, None)
    mc_prov=["If a student earns course credit, then the student completes the coursework.",
             "Every student earns course credit."]
    t("MC unique direct -> A",  MC_Q, mc_prov, MC_OPTS, "A")
    mc_meta=["If a student earns course credit, then the student completes the coursework."]  # A/C unprovable
    t("MC meta cannot-determine -> B", MC_Q, mc_meta, MC_OPTS, "B")
    t("MC conditional distractor must NOT win -> B", MC_Q, mc_meta, MC_OPTS, "B")
    npass=sum(1 for r in res if r[0])
    print(f"UNIT TESTS: {npass}/{len(res)} passed")
    for ok,name,exp,got,why,pu in res:
        print(("  PASS " if ok else "  FAIL ")+f"{name}: exp={exp} got={got} rule={why} prem={pu}")
    return npass==len(res)

if __name__=="__main__":
    import sys
    ok=_run_unit_tests()
    (a,pu,why),_=verify_v38_live("Does at least one student receive a scholarship?",
                                 ["Every student receives a scholarship."], ["Yes","No","Uncertain"])
    print("\nlive-format smoke (NL-only, no FOL):", a, pu, why)
    sys.exit(0 if ok else 1)
