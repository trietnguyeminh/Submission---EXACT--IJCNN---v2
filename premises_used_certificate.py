# premises_used ANSWER-AWARE proof-certificate (live-safe). Type1 P2 +2.0pp on Phase-1, 0 regression.
# -*- coding: utf-8 -*-
"""v40.x entity-grounded conjunctive Horn engine for the REAL Phase-1 distribution.
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
ACTION_VERBS={'receives','receive','provides','provide','shows','show','states','state','monitors','monitor','captures','capture','enters','enter','requires','require','needs','need','gains','gain','completed','complete','contains','contain','reports','report','releases','release','passes','pass','improves','improve','supports','support','recommends','recommend','administered','administer','approved','approve'}
_NEGWORD=re.compile(r'\b(no|not|cannot|can not|lacks?|without|isn\'t|aren\'t|never|nor|incomplete|missing|lacking)\b',re.I)
def to_literal(clause):
    c=clause.strip().rstrip('.').strip()
    c=_LEAD.sub('',c).strip()
    neg=bool(re.search(r"\b(no|not|cannot|can not|never|lacks?|without|isn't|aren't|incomplete|missing|lacking|nor|un(?:able|verified|established))\b",c,re.I))
    m=_VERB.search(c)
    pred=c[m.end():].strip() if m else c
    verb=(m.group(1).lower() if m else '')
    if m and verb in ACTION_VERBS:
        pred = verb + ' ' + pred
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
    # Universal relative rule: Every/All <role> <condition> <verb> <consequent>
    m2=re.search(r'^\s*(every|all)\s+[a-zA-Z]+s?\s+(.+?)\s+\b(can|may|must|should|will|would|receives?|gets?|gains?|provides?|captures?|monitors?|requires?|needs?|is|are)\b\s+(.+)$',s,re.I)
    if m2:
        cond=m2.group(2).strip()
        cons=(m2.group(3)+" "+m2.group(4)).strip()
        litc=to_literal(cond); litd=to_literal(cons)
        if litc and litd: return ('rule',[litc],litd)
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

_META_RE=re.compile(r"\b(not (?:yet )?(?:established|confirmed|verified|approved|cleared|determined)|cannot be (?:established|confirmed)|unsupported|is not established|no premise|undetermined|not (?:available|present))\b",re.I)
def decompose_option(opt):
    t=re.sub(r'^\s*[A-Da-d][.):]\s*','',str(opt)).strip()
    t=re.split(r'\bbecause\b', t, maxsplit=1, flags=re.I)[0].strip()  # drop causal justification
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
                if have and val==True: status='DISPROVEN'; break
            else:
                if have and val==(not neg): path+=facts[a][1]
                elif have and val==(neg): status='DISPROVEN'; break
                else: status='UNSUP'; break
        res[lab]=(status, sorted(set(path)))
    proven=[l for l in res if res[l][0]=='PROVEN']
    if len(proven)==1: return proven[0],res[proven[0]][1],'entity_unique_proof',res
    return None,[],('multiple' if proven else 'none'),res

def _opt_texts(q):
    return [o[1].strip().replace(chr(10)," ") for o in re.findall(r"(?:^|\n)\s*([A-D])[.)]\s*(.+?)(?=\n\s*[A-D][.)]|\Z)",str(q),flags=re.S)]

# ============ ANSWER-AWARE premises_used proof-certificate (v2) ============
# Phản biện chồng (2026-06-20): cert PHẢI gắn với answer đang trả, không union mọi option.
# Policy:
#   MC (A/B/C/D hoặc option-text): chỉ trace premises của ĐÚNG option được trả -> proof_trace.
#   YNU (Yes/No/Unknown/Uncertain): KHÔNG đụng (chưa có meta/no-premise prover tin cậy) -> giữ old.
#   Guards: proof-based only; len(cert)>=len(old) (chống under-trace); cap MAX_CERT_LEN (chống cert nhiễu dài).
#   Never change answer; chỉ cải thiện premises_used.
MAX_CERT_LEN = 12
def _resolve_option_index(answer, opts):
    """Map a returned answer (letter A-D OR full/partial option text) to an option index. None if not MC."""
    a=str(answer).strip()
    if re.fullmatch(r"[A-Da-d]", a):
        i="ABCD".index(a.upper()); return i if i<len(opts) else None
    if a.lower() in {"yes","no","unknown","uncertain",""}:
        return None                                # YNU: never override here
    norm=lambda s: re.sub(r"[^a-z0-9]","",str(s).lower())
    na=norm(a)
    if not na: return None
    for i,o in enumerate(opts):                    # exact then containment match on option text
        if norm(o)==na: return i
    for i,o in enumerate(opts):
        if na and (na in norm(o) or norm(o) in na): return i
    return None
def premises_used_certificate(answer, question, premises, options):
    """Return (cert_indices, source). Trace ONLY the returned option's atoms. MC only."""
    opts=_opt_texts(question) or options
    if not opts: return [], "no_options"
    i=_resolve_option_index(answer, opts)
    if i is None: return [], "skip_ynu"            # YNU or unresolved -> keep old
    atoms=[lit[0] for lit,_m,_t in decompose_option(opts[i]) if lit]
    if not atoms: return [], "no_atom"
    try: facts=solve_entity(premises)
    except TypeError: facts=solve_entity(premises,None)
    used=set(); proven=False
    for at in atoms:
        if at in facts: used|=set(facts[at][1]); proven=True
    return (sorted(used),"answer_option_proof_trace") if proven else ([], "answer_not_derivable")
def apply_premises_certificate(premises_used, answer, question, premises, options):
    """ANSWER-AWARE live-safe override. Returns improved premises_used or the original unchanged."""
    old=list(premises_used or [])
    c,src=premises_used_certificate(answer, question, premises, options)
    if src!="answer_option_proof_trace": return old          # not a real proof trace -> keep old
    if not c: return old
    if len(c)<len(old): return old                            # anti under-trace
    if len(c)>MAX_CERT_LEN: return old                        # anti noisy long cert
    return c
if __name__!="__main__":
    print("premises_used ANSWER-AWARE certificate ready (MC-only, proof-trace, cap=%d)"%MAX_CERT_LEN)
