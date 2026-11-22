"""Specialist diagnosers. Each one reads Signals and returns a Diagnosis or None.

They are plain functions so they can be unit-tested without the graph, and the
graph stays a thin orchestration layer over them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .signals import Signals

CATEGORIES = ["data_residency", "identity", "quota", "model_limits", "retrieval", "network", "deployment_config"]

# Country -> Google Cloud regions that keep data in-country (config can override with allowed_regions).
RESIDENCY = {"QA": {"me-central1"}, "SA": {"me-central2"}}

# Well-known Entra ID (Azure AD) sign-in error codes.
AADSTS = {
    "65001": ("consent_required", "The app has no user or admin consent for the API it calls."),
    "700016": ("app_not_found", "The client ID is not registered in this tenant (wrong tenant or app ID)."),
    "7000215": ("bad_secret", "The client secret is invalid or has expired."),
    "50011": ("redirect_mismatch", "The redirect URI does not match the app registration."),
    "500011": ("resource_not_found", "The resource / audience in the token request does not exist in this tenant."),
}


@dataclass
class Diagnosis:
    category: str
    root_cause: str
    fix_steps: list[str]
    confidence: float
    evidence: list[str] = field(default_factory=list)
    risky_fix: bool = False  # changes permissions or infra: needs human approval


def _ev(s: Signals, *keys: str) -> list[str]:
    return [s.evidence[k] for k in keys if k in s.evidence]


def identity(s: Signals) -> Diagnosis | None:
    for code in s.aadsts:
        if code in AADSTS:
            key, why = AADSTS[code]
            fixes = {
                "consent_required": ["Grant admin consent for the API permission in Entra ID > App registrations > API permissions.",
                                     "Re-request the token after consent; cached tokens keep the old scopes."],
                "app_not_found": ["Check the tenant ID and client ID pair in config; they must come from the same tenant.",
                                  "For multi-tenant apps, provision the service principal in the customer tenant."],
                "bad_secret": ["Rotate the client secret, store it in Key Vault, and reference it, never inline.",
                               "Prefer a managed identity or certificate credential so it cannot silently expire."],
                "redirect_mismatch": ["Add the exact redirect URI (scheme, host, path, trailing slash) to the app registration."],
                "resource_not_found": ["Request the token for the right resource, e.g. https://cognitiveservices.azure.com/.default."],
            }[key]
            return Diagnosis("identity", f"AADSTS{code}: {why}", fixes, 0.95,
                             [ln for ln in s.evidence.values() if f"AADSTS{code}" in ln] or [f"AADSTS{code}"],
                             risky_fix=key in {"consent_required", "bad_secret"})
    if "invalid_audience" in s.keywords:
        return Diagnosis("identity", "The access token was issued for a different audience than the API expects.",
                         ["Decode the token and compare its aud claim with the API's expected audience.",
                          f"Request scope '{s.config.get('expected_audience', '<api>')}/.default' instead of the current one."],
                         0.9, _ev(s, "invalid_audience"))
    if "missing_scope" in s.keywords or "consent_required" in s.keywords:
        return Diagnosis("identity", "The identity lacks a permission (scope or role) the call needs.",
                         ["List the token's scp/roles claims and compare with the API's required permission.",
                          "Add the permission (least privilege) and grant admin consent."],
                         0.85, _ev(s, "missing_scope", "consent_required"), risky_fix=True)
    if "expired_token" in s.keywords:
        return Diagnosis("identity", "A cached token expired and was not refreshed.",
                         ["Acquire tokens per request through the SDK credential (it caches and refreshes).",
                          "Remove any token stored in config or environment variables."],
                         0.85, _ev(s, "expired_token"))
    if "wif_token" in s.keywords:
        return Diagnosis("identity", "Workload Identity Federation could not exchange the external token for a Google credential.",
                         ["Check the workload identity pool provider's audience and attribute mapping match the external token.",
                          "Grant the external identity roles/iam.workloadIdentityUser on the service account it impersonates."],
                         0.85, _ev(s, "wif_token"), risky_fix=True)
    if "gcp_permission_denied" in s.keywords:
        sa = s.config.get("service_account", "the service account")
        return Diagnosis("identity", f"IAM: {sa} lacks the permission the Vertex AI / Google Cloud call needs.",
                         [f"Grant {sa} the narrowest role that holds the permission named in the error (e.g. roles/aiplatform.user for predictions).",
                          "Grant it on the project or resource that owns the model, not the caller's project, and allow a few minutes to propagate."],
                         0.9, _ev(s, "gcp_permission_denied"), risky_fix=True)
    if 401 in s.http_codes:
        return Diagnosis("identity", "Unauthenticated (401) with no more specific error in the logs.",
                         ["Log the full error body; check the credential type and tenant."], 0.5)
    return None


def quota(s: Signals) -> Diagnosis | None:
    if "gcp_resource_exhausted" in s.keywords:
        return Diagnosis("quota", "Google Cloud quota exhausted (RESOURCE_EXHAUSTED) for the model in this region.",
                         ["Retry with exponential backoff; Vertex AI quota is per project, per region, per model.",
                          "Request a quota increase in IAM & Admin > Quotas, or use Provisioned Throughput for steady production load."],
                         0.9, _ev(s, "gcp_resource_exhausted"))
    if 429 in s.http_codes or "rate_limited" in s.keywords:
        wait = f" The service asked to wait {s.retry_after_s}s." if s.retry_after_s else ""
        return Diagnosis("quota", "Requests exceed the deployment's rate limit (tokens or requests per minute)." + wait,
                         ["Honour Retry-After with exponential backoff and jitter.",
                          "Cap concurrency, and lower max_tokens so each call reserves less quota.",
                          "If sustained, request a quota increase or add a second deployment behind a load balancer."],
                         0.9, _ev(s, "rate_limited"))
    return None


def model_limits(s: Signals) -> Diagnosis | None:
    if "content_filter" in s.keywords:
        return Diagnosis("model_limits", "The provider's content filter blocked the prompt or completion.",
                         ["Log which filter category fired; check whether retrieved documents carry the trigger.",
                          "Handle the filtered finish reason in code and show the user a clear message."],
                         0.9, _ev(s, "content_filter"))
    if "context_length" in s.keywords:
        limit = s.config.get("context_window")
        over = max(s.token_counts) if s.token_counts else None
        detail = f" Request had about {over} tokens against a {limit} window." if over and limit else ""
        return Diagnosis("model_limits", "The prompt exceeds the model's context window." + detail,
                         ["Trim retrieved chunks to the top-k that fit a token budget.",
                          "Summarise conversation history beyond the last few turns."],
                         0.9, _ev(s, "context_length"))
    return None


def retrieval(s: Signals) -> Diagnosis | None:
    cfg = s.config
    emb, idx = cfg.get("embedding_dims"), cfg.get("index_dims")
    if "dimension_mismatch" in s.keywords or (emb and idx and emb != idx):
        return Diagnosis("retrieval", f"Embedding model output ({emb}) does not match the index vector size ({idx}).",
                         ["Use the same embedding model for indexing and querying.",
                          "If the model changed, re-embed and rebuild the index; never mix vectors from two models."],
                         0.95, _ev(s, "dimension_mismatch"))
    if "index_not_found" in s.keywords:
        return Diagnosis("retrieval", f"The search index '{cfg.get('index_name', '?')}' does not exist in this environment.",
                         ["Check the index name per environment (dev/test/prod) in config.",
                          "Add the index build to the deployment pipeline so it exists before the app starts."],
                         0.9, _ev(s, "index_not_found"))
    if "empty_retrieval" in s.keywords:
        return Diagnosis("retrieval", "Retrieval returned no documents, so the model answered without grounding.",
                         ["Run the query directly against the index to separate indexing from query problems.",
                          "Check the filter (tenant, language, security trimming) is not excluding everything.",
                          "Refuse to answer when nothing is retrieved instead of letting the model guess."],
                         0.8, _ev(s, "empty_retrieval"))
    return None


def network(s: Signals) -> Diagnosis | None:
    if "vpc_service_controls" in s.keywords:
        return Diagnosis("network", "VPC Service Controls blocked the call: the caller is outside the service perimeter.",
                         ["Look up the vpcServiceControlsUniqueIdentifier in the audit logs to see which rule fired.",
                          "Add an ingress rule for the caller's identity and source, or run the caller inside the perimeter; do not remove the perimeter."],
                         0.9, _ev(s, "vpc_service_controls"), risky_fix=True)
    if "private_endpoint" in s.keywords:
        return Diagnosis("network", "The resource only accepts private traffic and the caller is outside the VNet.",
                         ["Run the app inside the VNet (VNet integration) or allow its subnet.",
                          "Confirm private DNS resolves the endpoint to a private IP from the caller."],
                         0.9, _ev(s, "private_endpoint"), risky_fix=True)
    if "dns" in s.keywords:
        return Diagnosis("network", "The endpoint hostname does not resolve from where the app runs.",
                         ["Check for a typo in the endpoint and the private DNS zone link to the VNet."],
                         0.85, _ev(s, "dns"))
    if "timeout" in s.keywords:
        return Diagnosis("network", "Calls time out before the service responds.",
                         ["Stream responses for long generations; raise the client timeout only for those calls.",
                          "Check egress rules and proxy settings between the app and the endpoint."],
                         0.7, _ev(s, "timeout"))
    return None


def deployment_config(s: Signals) -> Diagnosis | None:
    if "deployment_not_found" in s.keywords or (404 in s.http_codes and "deployment" in s.config):
        return Diagnosis("deployment_config",
                         f"The model deployment '{s.config.get('deployment', '?')}' does not exist on this endpoint.",
                         ["Use the deployment name, not the model name, and check it per region/resource.",
                          "Keep deployment names in config per environment, never hard-coded."],
                         0.9, _ev(s, "deployment_not_found"))
    return None


def data_residency(s: Signals) -> Diagnosis | None:
    country, region = s.config.get("data_residency"), s.config.get("region")
    if not country or not region:
        return None
    allowed = set(s.config.get("allowed_regions") or RESIDENCY.get(country, set()))
    if allowed and region not in allowed:
        return Diagnosis("data_residency",
                         f"Data must stay in {country} but the model endpoint runs in {region} (allowed: {', '.join(sorted(allowed))}).",
                         [f"Deploy the model and vector index in {', '.join(sorted(allowed))} and pin the client to that regional endpoint.",
                          "Check every hop (embeddings, logging, evaluation exports) for the same constraint, not only the model call.",
                          "Record the decision for the customer's compliance team before go-live."],
                         0.95, [f"config: data_residency={country}, region={region}"], risky_fix=True)
    return None


SPECIALISTS = {
    "data_residency": data_residency,
    "identity": identity, "quota": quota, "model_limits": model_limits,
    "retrieval": retrieval, "network": network, "deployment_config": deployment_config,
}

# Cheap triage scores: which specialist to ask first.
TRIAGE = {
    "data_residency": (set(), set()),
    "identity": ({"invalid_audience", "missing_scope", "expired_token", "consent_required", "gcp_permission_denied", "wif_token"}, {401}),
    "quota": ({"rate_limited", "gcp_resource_exhausted"}, {429}),
    "model_limits": ({"context_length", "content_filter"}, set()),
    "retrieval": ({"index_not_found", "dimension_mismatch", "empty_retrieval"}, set()),
    "network": ({"timeout", "dns", "private_endpoint", "vpc_service_controls"}, set()),
    "deployment_config": ({"deployment_not_found"}, {404}),
}


def triage(s: Signals) -> list[str]:
    """Rank categories by evidence. Ties keep the order in CATEGORIES."""
    scores = {}
    for cat, (kws, codes) in TRIAGE.items():
        score = 2 * len(kws & s.keywords) + len(codes & set(s.http_codes))
        if cat == "identity" and s.aadsts:
            score += 3
        if cat == "data_residency" and data_residency(s):
            score += 10  # a residency breach outranks any runtime error: fix it first
        if cat == "retrieval" and s.config.get("embedding_dims") and s.config.get("index_dims") \
                and s.config["embedding_dims"] != s.config["index_dims"]:
            score += 3
        scores[cat] = score
    return [c for c in sorted(CATEGORIES, key=lambda c: -scores[c]) if scores[c] > 0]
