"""Customer-facing summary in English or Arabic (Modern Standard Arabic).

The technical evidence stays in English (log lines are English); the framing a
customer reads is in their language.
"""
from __future__ import annotations

CAT_AR = {
    "data_residency": "إقامة البيانات داخل الدولة",
    "identity": "الهوية والصلاحيات",
    "quota": "حدود الاستخدام",
    "model_limits": "حدود النموذج",
    "retrieval": "البحث في المستندات",
    "network": "الشبكة",
    "deployment_config": "إعدادات النشر",
}
STATUS = {
    "en": {"diagnosed": "Diagnosed", "approved": "Diagnosed, fix approved",
           "rejected": "Diagnosed, fix rejected by approver", "escalated": "Escalated to engineering"},
    "ar": {"diagnosed": "تم التشخيص", "approved": "تم التشخيص واعتماد الحل",
           "rejected": "تم التشخيص ورفض الحل من المعتمد", "escalated": "تم التصعيد إلى فريق الهندسة"},
}


def render(state: dict, lang: str = "en") -> str:
    lang = "ar" if lang == "ar" else "en"
    status = state.get("status", "escalated")
    d = state.get("diagnosis")
    lines = []
    if lang == "en":
        lines.append(f"Status: {STATUS['en'][status]}")
        if d:
            lines += [f"Area: {d['category']}", f"Root cause: {d['root_cause']}", "Next steps:"]
            lines += [f"  {i}. {step}" for i, step in enumerate(d["fix_steps"], 1)]
        else:
            lines.append("No confident diagnosis from the logs provided. Checked: " + ", ".join(state.get("tried", [])) + ".")
            lines.append("Please share the full error body and the request ID.")
    else:
        lines.append(f"الحالة: {STATUS['ar'][status]}")
        if d:
            lines += [f"المجال: {CAT_AR[d['category']]}", f"السبب الجذري (بالإنجليزية): {d['root_cause']}",
                      f"عدد خطوات الحل: {len(d['fix_steps'])}، مرفقة بالتفصيل للفريق التقني."]
        else:
            lines.append("لم نصل إلى تشخيص مؤكد من السجلات المرسلة.")
            lines.append("نرجو إرسال نص الخطأ كاملاً ورقم الطلب (Request ID).")
    if d and d.get("evidence"):
        lines.append(("Evidence:" if lang == "en" else "الدليل من السجلات:"))
        lines += [f"  > {e}" for e in d["evidence"][:3]]
    if state.get("approver_note"):
        lines.append(("Approver note: " if lang == "en" else "ملاحظة المعتمد: ") + state["approver_note"])
    return "\n".join(lines)
