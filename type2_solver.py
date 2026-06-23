# type2_solver.py — deterministic physics/math solver bank for EXACT 2026 Type2.
# Family-classifier first -> formula bank -> (value, ASCII unit). Unrecognized -> return None (caller LLM-fallback).
# -*- coding: utf-8 -*-
import re, math

# ---------- unit / number parsing ----------
_PREFIX = {'n':1e-9,'u':1e-6,'µ':1e-6,'μ':1e-6,'m':1e-3,'c':1e-2,'k':1e3,'M':1e6,'G':1e9,'p':1e-12}
def _num(tok):
    """Parse a numeric token possibly like '9.0 × 10^9', '3.34e5', '+4.0', '1.5'."""
    s=tok.strip().replace('×','x').replace('·','').replace(' ','')
    s=s.replace('x10^','e').replace('x10','e').replace('X10^','e').replace('*10^','e')
    s=re.sub(r'\^','',s)
    try: return float(s)
    except: 
        m=re.match(r'^([+-]?\d*\.?\d+)e([+-]?\d+)$',s)
        if m: return float(m.group(1))*10**int(m.group(2))
        return None

# unit -> (SI factor, dimension tag)
def _unit_si(val, unit):
    u=unit.strip()
    u=u.rstrip('.,;)')
    # compound first
    table={
        'F':1,'mF':1e-3,'uF':1e-6,'µF':1e-6,'μF':1e-6,'nF':1e-9,'pF':1e-12,
        'C':1,'mC':1e-3,'uC':1e-6,'µC':1e-6,'μC':1e-6,'nC':1e-9,'pC':1e-12,
        'V':1,'kV':1e3,'MV':1e6,'mV':1e-3,
        'A':1,'mA':1e-3,
        'Ω':1,'ohm':1,'kΩ':1e3,'kohm':1e3,
        'H':1,'mH':1e-3,'uH':1e-6,
        'Hz':1,'kHz':1e3,'MHz':1e6,
        'J':1,'kJ':1e3,'MJ':1e6,'mJ':1e-3,'uJ':1e-6,'µJ':1e-6,
        'W':1,'kW':1e3,'mW':1e-3,
        'N':1,'kN':1e3,
        'kg':1,'g':1e-3,
        'm':1,'cm':1e-2,'mm':1e-3,'km':1e3,
        'mol':1,
        'K':1,
        's':1,'min':60,'minute':60,'minutes':60,'h':3600,
        'Pa':1,'kPa':1e3,'MPa':1e6,'GPa':1e9,
        'T':1,
    }
    if u in table: return val*table[u]
    return val  # unknown unit: leave as-is

# ---------- extract labelled vars + role tokens ----------
_TOKEN = re.compile(
    r'(?P<label>[A-Za-zρ][A-Za-z0-9]*)?\s*=?\s*'
    r'(?P<val>[+-]?\d*\.?\d+(?:\s*(?:×|x|\*)\s*10\s*\^?\s*[+-]?\d+)?(?:e[+-]?\d+)?)'
    r'\s*(?P<unit>(?:°C|μF|µF|uF|nF|pF|mF|F|μC|µC|uC|nC|pC|mC|C|kV|mV|V|mA|A|kΩ|kohm|Ω|ohm|mH|uH|H|kHz|MHz|Hz|kJ|MJ|mJ|µJ|uJ|J|kW|mW|W|kN|N|kg|g|km|cm|mm|m/s\^?2|m/s²|m/s|mol|min(?:ute)?s?|m|s|K|h|MPa|GPa|kPa|Pa|T)\b)?'
)
def parse_vars(text):
    text=text.replace('μ','u').replace('µ','u')
    named={}; roles={'mass':[],'speed':[],'accel':[],'force':[],'time':[],'dist':[],'volt':[],
                     'curr':[],'res':[],'cap':[],'charge':[],'induct':[],'freq':[],'temp':[],
                     'dT':[],'mol':[],'power':[],'energy':[],'cheat':[],'latent':[],'turns':[],'len':[],'area':[]}
    # specific heat / latent appear as "4200 J/(kg" or "3.34e5 J/kg"
    for m in re.finditer(r'([0-9.]+(?:\s*(?:×|x)\s*10\^?[+-]?\d+)?)\s*J\s*/\s*\(?\s*kg\s*[·*]?\s*°?C', text):
        v=_num(m.group(1)); 
        if v is not None: roles['cheat'].append(v)
    for m in re.finditer(r'([0-9.]+(?:\s*(?:×|x)\s*10\^?[+-]?\d+)?)\s*J\s*/\s*kg(?!\s*[·*]?\s*°?C)', text):
        v=_num(m.group(1)); 
        if v is not None: roles['latent'].append(v)
    for m in _TOKEN.finditer(text):
        lab=m.group('label'); raw=m.group('val'); unit=(m.group('unit') or '').strip()
        v=_num(raw)
        if v is None: continue
        si=_unit_si(v,unit) if unit else v
        if lab and lab not in ('x','X'):
            named.setdefault(lab,si)
        u=unit.lower().replace(' ','')
        if u in('kg','g'): roles['mass'].append(si)
        elif u=='m/s': roles['speed'].append(si)
        elif u in('m/s^2','m/s²','m/s2'): roles['accel'].append(si)
        elif u in('n','kn'): roles['force'].append(si)
        elif u in('s','min','mins','minute','minutes','h'): roles['time'].append(si)
        elif u in('m','cm','mm','km'): roles['dist'].append(si); roles['len'].append(si)
        elif u in('v','kv','mv'): roles['volt'].append(si)
        elif u in('a','ma'): roles['curr'].append(si)
        elif u in('ω','ohm','kω','kohm'): roles['res'].append(si)
        elif u in('f','mf','uf','nf','pf'): roles['cap'].append(si)
        elif u in('c','mc','uc','nc','pc'): roles['charge'].append(si)
        elif u in('h','mh','uh'): roles['induct'].append(si)
        elif u in('hz','khz','mhz'): roles['freq'].append(si)
        elif u=='k': roles['temp'].append(si)
        elif u=='°c': roles['dT'].append(si)
        elif u=='mol': roles['mol'].append(si)
        elif u in('w','kw','mw'): roles['power'].append(si)
        elif u in('j','kj','mj','uj'): roles['energy'].append(si)
        elif u in('pa','kpa'): roles['volt']  # not used
    return named, roles, text

def g(named, roles, *keys):
    for k in keys:
        if k in named: return named[k]
    return None

K_COULOMB=9.0e9
G_DEFAULT=9.8

# ---------- formatter: numeric, ASCII unit ----------
def _fmt(value, unit):
    # Plain ASCII decimal (grader numeric-tolerant; '× 10^' risks weak parsers). Scientific only for |v|<1e-4.
    if value==0: return "0", unit
    av=abs(value)
    if av < 1e-4:
        m=value; e=0
        while abs(m)>=10: m/=10; e+=1
        while abs(m)<1: m*=10; e-=1
        return f"{round(m,3):g} × 10^{e}", unit
    exp=math.floor(math.log10(av)); dec=max(0, 6-1-exp)
    r=round(value, dec)
    s=(f"{r:.{dec}f}" if dec>0 else f"{int(round(r))}")
    if '.' in s: s=s.rstrip('0').rstrip('.')
    return s, unit

# ---------- solver rules ----------
def solve_type2_deterministic(query, premises=None, options=None):
    q=str(query or ""); ql=q.lower()
    text=q+" "+" ".join(premises or [])
    named, roles, T = parse_vars(text)
    def one(role): 
        a=roles.get(role) or []
        return a[0] if a else None
    def two(role):
        a=roles.get(role) or []
        return (a[0],a[1]) if len(a)>=2 else (None,None)
    log={"family":None,"vars":{},"formula":None,"raw":None}
    def out(value,unit,family,formula,raw):
        s,u=_fmt(value,unit)
        return {"answer":s,"unit":u,"premises_used":[],"reasoning":{"source":"type2_deterministic","family":family,"formula":formula},
                "_log":{"family":family,"formula":formula,"raw_value":value,"normalized":s,"unit":u,"vars":raw,"route":"deterministic"}}

    # ---- ELECTRICITY ----
    # capacitor energy E=0.5 C U^2
    if ('energy' in ql) and ('capacitor' in ql):
        C=g(named,roles,'C') or one('cap'); U=g(named,roles,'U','V') or one('volt')
        if C and U: return out(0.5*C*U*U,'J','cap_energy','0.5*C*U^2',{'C':C,'U':U})
    # capacitance from Q,U
    if 'capacitance' in ql and ('charge' in ql or g(named,roles,'Q')):
        Q=g(named,roles,'Q') or one('charge'); U=g(named,roles,'U','V') or one('volt')
        if Q and U: return out((Q/U)/1e-6,'uF','capacitance','Q/U',{'Q':Q,'U':U})
    # series capacitors charge
    if 'capacitor' in ql and 'series' in ql and 'charge' in ql:
        C1=g(named,roles,'C1'); C2=g(named,roles,'C2'); caps=roles.get('cap') or []
        if C1 is None and len(caps)>=2: C1,C2=caps[0],caps[1]
        U=g(named,roles,'U','V') or one('volt')
        if C1 and C2 and U:
            Ceq=1/(1/C1+1/C2); return out((Ceq*U)/1e-6,'uC','cap_series_charge','Ceq=C1C2/(C1+C2); Q=Ceq*U',{'C1':C1,'C2':C2,'U':U})
    # Coulomb force
    if ('force' in ql) and ('charge' in ql or g(named,roles,'q1')):
        q1=g(named,roles,'q1') or (roles['charge'][0] if roles['charge'] else None)
        q2=g(named,roles,'q2') or (roles['charge'][1] if len(roles['charge'])>1 else None)
        r=g(named,roles,'r','d') or one('dist'); k=g(named,roles,'k') or K_COULOMB
        if q1 and q2 and r: return out(k*abs(q1*q2)/(r*r),'N','coulomb_force','k|q1 q2|/r^2',{'q1':q1,'q2':q2,'r':r,'k':k})
    # electric field at midpoint (two charges, distance apart)
    if 'electric field' in ql:
        charges=roles.get('charge') or []; dist=one('dist'); k=g(named,roles,'k') or K_COULOMB
        if len(charges)>=2 and dist:
            r=dist/2.0
            E=sum(k*abs(c)/(r*r) for c in charges[:2])  # equal/opposite at midpoint add
            return out(E,'N/C','efield_midpoint','sum k|qi|/(d/2)^2',{'q':charges[:2],'d':dist,'k':k})
        if len(charges)>=1 and (g(named,roles,'r','d') or dist):
            r=g(named,roles,'r','d') or dist; k=g(named,roles,'k') or K_COULOMB
            return out(k*abs(charges[0])/(r*r),'N/C','efield_point','k|q|/r^2',{'q':charges[0],'r':r,'k':k})
    # electric potential V = sum k qi / ri  (signed)
    if 'potential' in ql and ('charge' in ql or g(named,roles,'q1')) and 'difference' not in ql:
        k=g(named,roles,'k') or K_COULOMB
        q1=g(named,roles,'q1'); q2=g(named,roles,'q2')
        ch=roles.get('charge') or []
        if q1 is None and ch: q1=ch[0]
        if q2 is None and len(ch)>1: q2=ch[1]
        dd=roles.get('dist') or []
        r1=dd[0] if len(dd)>0 else None; r2=dd[1] if len(dd)>1 else None
        if q1 and r1:
            V=k*q1/r1 + (k*q2/r2 if (q2 and r2) else 0)
            return out(V,'V','e_potential','sum k*qi/ri',{'q1':q1,'r1':r1,'q2':q2,'r2':r2,'k':k})
    # resistor electrical energy E=V^2/R * t
    if 'resistor' in ql and 'energy' in ql:
        R=g(named,roles,'R') or one('res'); U=g(named,roles,'U','V') or one('volt'); t=one('time')
        if R and U and t: return out((U*U/R)*t,'J','resistor_energy','(U^2/R)*t',{'R':R,'U':U,'t':t})
    # series resistor current
    if 'series' in ql and ('current' in ql) and (g(named,roles,'R1') or len(roles.get('res') or [])>=2):
        R1=g(named,roles,'R1'); R2=g(named,roles,'R2'); rs=roles.get('res') or []
        if R1 is None and len(rs)>=2: R1,R2=rs[0],rs[1]
        U=g(named,roles,'U','V') or one('volt')
        if R1 and R2 and U: return out(U/(R1+R2),'A','series_current','U/(R1+R2)',{'R1':R1,'R2':R2,'U':U})
    # parallel resistor current
    if 'parallel' in ql and 'current' in ql and (g(named,roles,'R1') or len(roles.get('res') or [])>=2):
        R1=g(named,roles,'R1'); R2=g(named,roles,'R2'); rs=roles.get('res') or []
        if R1 is None and len(rs)>=2: R1,R2=rs[0],rs[1]
        U=g(named,roles,'U','V') or one('volt')
        if R1 and R2 and U: return out(U*(1/R1+1/R2),'A','parallel_current','U*(1/R1+1/R2)',{'R1':R1,'R2':R2,'U':U})
    # power P=U I
    if 'power' in ql and (g(named,roles,'I') or roles.get('curr')) and (g(named,roles,'U','V') or roles.get('volt')):
        I=g(named,roles,'I') or one('curr'); U=g(named,roles,'U','V') or one('volt')
        if I and U: return out(U*I,'W','power_ui','U*I',{'U':U,'I':I})
    # resistance from P,I :  R=P/I^2
    if 'resistance' in ql and ('dissipat' in ql or 'power' in ql) and (g(named,roles,'P') or roles.get('power')):
        P=g(named,roles,'P') or one('power'); I=g(named,roles,'I') or one('curr')
        if P and I: return out(P/(I*I),'ohm','resistance_pi','P/I^2',{'P':P,'I':I})
    # resistance from resistivity R=rho l / S
    if 'resistance' in ql and ('resistivity' in ql or 'rho' in ql or g(named,roles,'rho')):
        rho=g(named,roles,'rho'); l=g(named,roles,'l') or one('len'); S=g(named,roles,'S')
        # area S in mm^2 -> m^2 ; but rho given in ohm*mm^2/m cancels; handle unit-native
        mS=re.search(r'S\s*=\s*([0-9.]+)\s*mm\^?2', text)
        Sv=float(mS.group(1))*1e-6 if mS else S
        mrho=re.search(r'rho\s*=\s*([0-9.]+)\s*ohm', text)
        # if rho in ohm*mm^2/m and S in mm^2, R = rho*l/S with S in mm^2
        if mrho and mS:
            rhov=float(mrho.group(1)); Smm=float(mS.group(1)); 
            if l: return out(rhov*l/Smm,'ohm','resistivity','rho*l/S (mm^2 native)',{'rho':rhov,'l':l,'S_mm2':Smm})
        if rho and l and Sv: return out(rho*l/Sv,'ohm','resistivity','rho*l/S',{'rho':rho,'l':l,'S':Sv})
    # work W=qU (charge through potential difference)
    if 'work' in ql and ('charge' in ql or g(named,roles,'q')) and ('potential difference' in ql or g(named,roles,'U','V')):
        qv=g(named,roles,'q') or one('charge'); U=g(named,roles,'U','V') or one('volt')
        if qv and U: return out((qv*U)/1e-6,'uJ','work_qu','q*U',{'q':qv,'U':U})
    # LC resonant frequency
    if ('resonant' in ql or 'lc circuit' in ql) and g(named,roles,'L') and g(named,roles,'C'):
        L=g(named,roles,'L'); C=g(named,roles,'C')
        return out(1/(2*math.pi*math.sqrt(L*C)),'Hz','lc_resonance','1/(2π√(LC))',{'L':L,'C':C})
    # inductive reactance XL=2 pi f L
    if 'inductive reactance' in ql and g(named,roles,'L') and (g(named,roles,'f') or roles.get('freq')):
        L=g(named,roles,'L'); f=g(named,roles,'f') or one('freq')
        return out(2*math.pi*f*L,'ohm','inductive_reactance','2πfL',{'L':L,'f':f})

    # ---- MECHANICS ----
    # kinematics: acceleration from s=ut+0.5 a t^2
    if 'acceleration' in ql and ('travels' in ql or 'distance' in ql) and roles.get('time'):
        u=one('speed'); s=one('dist'); t=one('time')
        if u is not None and s and t: return out(2*(s-u*t)/(t*t),'m/s^2','kinematics_accel','a=2(s-ut)/t^2',{'u':u,'s':s,'t':t})
    # braking distance d=v^2/(2a)
    if ('braking distance' in ql or ('distance' in ql and 'brake' in ql)):
        v=one('speed'); a=one('accel')
        if v and a: return out(v*v/(2*abs(a)),'m','braking_distance','v^2/(2a)',{'v':v,'a':a})
    # elevator normal force N=m(g±a)
    if ('elevator' in ql or 'normal force' in ql) and roles.get('mass'):
        m=one('mass'); a=one('accel'); gg=g(named,roles,'g') or G_DEFAULT
        if m and a is not None:
            sign=1 if ('upward' in ql or 'up' in ql) else (-1 if 'down' in ql else 1)
            return out(m*(gg+sign*a),'N','elevator_normal','m(g±a)',{'m':m,'a':a,'g':gg,'sign':sign})
    # work-energy final speed v=sqrt(2 F d/m)
    if ('final speed' in ql or 'final velocity' in ql) and roles.get('force') and roles.get('mass'):
        F=one('force'); d=one('dist'); m=one('mass')
        if F and d and m: return out(math.sqrt(2*F*d/m),'m/s','work_energy','v=√(2Fd/m)',{'F':F,'d':d,'m':m})
    # projectile max height h=v^2/(2g)
    if ('maximum height' in ql or 'max height' in ql) and ('upward' in ql or 'vertically' in ql):
        v=one('speed'); gg=g(named,roles,'g') or G_DEFAULT
        if v: return out(v*v/(2*gg),'m','projectile_height','v^2/(2g)',{'v':v,'g':gg})

    # ---- THERMO ----
    # calorimetry Q=mcΔT
    if 'heat' in ql and roles.get('cheat'):
        m=one('mass'); c=roles['cheat'][0]; dT=one('dT')
        if m and dT: return out(m*c*dT,'J','calorimetry','m*c*ΔT',{'m':m,'c':c,'dT':dT})
    # latent heat Q=mL
    if ('melt' in ql or 'fusion' in ql or 'latent' in ql) and roles.get('latent'):
        m=one('mass'); L=roles['latent'][0]
        if m: return out(m*L,'J','latent_heat','m*L',{'m':m,'L':L})
    # ideal gas P=nRT/V
    if 'pressure' in ql and g(named,roles,'n') and (g(named,roles,'T') or roles.get('temp')):
        n=g(named,roles,'n'); R=g(named,roles,'R') or 8.314; T=g(named,roles,'T') or one('temp')
        V=g(named,roles,'V')
        mV=re.search(r'V\s*=\s*([0-9.]+)\s*m', text)  # volume in m^3
        Vv=float(mV.group(1)) if mV else V
        if n and T and Vv: return out(n*R*T/Vv,'Pa','ideal_gas','nRT/V',{'n':n,'R':R,'T':T,'V':Vv})

    # ---- TRANSFORMER ----
    if 'transformer' in ql and g(named,roles,'N1') and g(named,roles,'N2'):
        N1=g(named,roles,'N1'); N2=g(named,roles,'N2'); U1=g(named,roles,'U1') or g(named,roles,'U','V') or one('volt')
        if U1: return out(U1*N2/N1,'V','transformer','U2=U1*N2/N1',{'N1':N1,'N2':N2,'U1':U1})

    # ---- OPTICS (thin lens) ----
    if 'lens' in ql and 'focal length' in ql:
        f=g(named,roles,'f'); dists=roles.get('dist') or []
        mf=re.search(r'focal length\s*(?:of\s*)?([0-9.]+)\s*cm', ql); 
        fcm=float(mf.group(1)) if mf else None
        mo=re.search(r'([0-9.]+)\s*cm in front', ql); do=float(mo.group(1)) if mo else (dists[0] if dists else None)
        if fcm and do:
            di=1/(1/fcm-1/do); return out(di,'cm','thin_lens','1/f=1/do+1/di',{'f':fcm,'do':do})
    return None
