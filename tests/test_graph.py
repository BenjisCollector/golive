from langgraph.types import Command

from deploy_doctor import build
from deploy_doctor.diagnose import triage
from deploy_doctor.signals import extract


def run(logs, config=None, lang="en", tid="t"):
    g = build()
    cfg = {"configurable": {"thread_id": tid}}
    return g, cfg, g.invoke({"logs": logs, "config": config or {}, "lang": lang}, cfg)


def test_risky_fix_pauses_for_approval_then_resumes():
    g, cfg, out = run("AADSTS65001: The user or administrator has not consented")
    assert "__interrupt__" in out
    assert "report" not in out
    done = g.invoke(Command(resume={"approve": True, "note": "CAB-1182"}), cfg)
    assert done["status"] == "approved"
    assert "CAB-1182" in done["report"]


def test_rejected_fix_is_reported_as_rejected():
    g, cfg, _ = run("403 Forbidden: Public network access is disabled", tid="r")
    done = g.invoke(Command(resume={"approve": False}), cfg)
    assert done["status"] == "rejected"
    assert "rejected" in done["report"]


def test_safe_fix_needs_no_approval():
    _, _, out = run("HTTP 429 Too Many Requests retry-after: 5")
    assert "__interrupt__" not in out
    assert out["diagnosis"]["category"] == "quota"
    assert "5s" in out["diagnosis"]["root_cause"]


def test_no_signal_escalates_instead_of_guessing():
    _, _, out = run("users say it feels slow")
    assert out["status"] == "escalated"
    assert out["diagnosis"] is None


def test_decoy_429_does_not_hide_the_real_cause():
    logs = "HTTP 429 (retried ok)\nretriever: no documents retrieved, empty context"
    _, _, out = run(logs)
    assert out["diagnosis"]["category"] == "retrieval"


def test_config_alone_catches_embedding_dimension_mismatch():
    s = extract("answers became irrelevant after the upgrade", {"embedding_dims": 3072, "index_dims": 1536})
    assert triage(s)[0] == "retrieval"


def test_arabic_customer_summary():
    _, _, out = run("HTTP 404 IndexNotFound: index 'hr-docs' was not found", {"index_name": "hr-docs"}, lang="ar")
    assert "الحالة: تم التشخيص" in out["report"]
    assert "البحث في المستندات" in out["report"]
    assert "IndexNotFound" in out["report"]  # evidence stays verbatim


def test_seven_digit_aadsts_code():
    assert extract("AADSTS7000215: Invalid client secret").aadsts == ["7000215"]
