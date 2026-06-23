# integration_snippet_predict_type1_live.py
# Put live_v38b_v39_wrapper.py beside your deploy notebook or in /kaggle/working.
from live_v38b_v39_wrapper import verify_v38_live

def symbolic_prehandler_type1(req, _field):
    qid = _field(req, "query_id")
    question = _field(req, "query", "") or ""
    premises = list(_field(req, "premises", []) or [])
    options = list(_field(req, "options", []) or [])

    (sa, sp, why), cert = verify_v38_live(question, premises, options)
    if sa is None:
        return None

    ans = sa
    # YNU compatibility: some EXACT examples use Uncertain instead of Unknown.
    if ans == "Unknown" and any(str(o).strip().lower() == "uncertain" for o in options):
        ans = "Uncertain"

    # IMPORTANT: for MC keep letter A/B/C/D. Do not map to option text unless scorer requires it.
    return {
        "query_id": qid,
        "answer": ans,
        "unit": "",
        "explanation": f"Derived by symbolic proof ({why}).",
        "premises_used": sp,
        "reasoning": {
            "source": "v38b_v39_symbolic",
            "rule": why,
            "canon_premises": cert.get("canon_premises", []),
        },
    }

# Example usage inside predict_type1_live(req):
# symbolic = symbolic_prehandler_type1(req, _field)
# if symbolic is not None:
#     return symbolic
# else:
#     ... existing LoRA + v35 path unchanged ...
