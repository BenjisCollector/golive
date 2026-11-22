from langgraph.types import Command

from golive import build
from golive.diagnose import triage
from golive.signals import extract


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


def test_gcp_permission_denied_names_the_service_account_and_needs_approval():
    g, cfg, out = run("403 Permission 'aiplatform.endpoints.predict' denied. [reason: IAM_PERMISSION_DENIED]",
                      {"service_account": "agent@p.iam.gserviceaccount.com"}, tid="gcp")
    assert "__interrupt__" in out
    done = g.invoke(Command(resume={"approve": True}), cfg)
    assert done["diagnosis"]["category"] == "identity"
    assert "agent@p.iam.gserviceaccount.com" in done["diagnosis"]["root_cause"]


def test_qatar_residency_breach_outranks_a_runtime_error():
    s = extract("HTTP 429 RESOURCE_EXHAUSTED", {"data_residency": "QA", "region": "europe-west4"})
    assert triage(s)[0] == "data_residency"


def test_in_region_qatar_deployment_is_not_flagged():
    s = extract("200 OK", {"data_residency": "QA", "region": "me-central1"})
    assert "data_residency" not in triage(s)
