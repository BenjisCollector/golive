"""Labelled incidents for the eval. Synthetic, written to match real error formats
(Entra ID AADSTS codes, OpenAI-compatible 429 bodies, Azure AI Search errors).

Each case: (id, expected, logs, config). expected is a category or "escalate".
Some cases carry decoy lines (a retried 429 next to the real cause) to check the
triage does not grab the loudest signal.
"""

CASES = [
    # identity
    ("id-01", "identity", "POST /token 400\nerror: AADSTS65001: The user or administrator has not consented to use the application", {}),
    ("id-02", "identity", "MSAL error AADSTS7000215: Invalid client secret provided.\nstatus=401", {}),
    ("id-03", "identity", "AADSTS700016: Application with identifier 'abc' was not found in the directory 'contoso'", {}),
    ("id-04", "identity", "HTTP 401 Unauthorized: invalid audience. Expected api://erp-api, got https://graph.microsoft.com",
     {"expected_audience": "api://erp-api"}),
    ("id-05", "identity", "graph call failed: Authorization_RequestDenied insufficient privileges to complete the operation\nHTTP 403", {}),
    ("id-06", "identity", "retrying... HTTP 429 (1/3)\nretry ok\nthen: HTTP 401 token is expired at 09:14Z", {}),
    ("id-07", "identity", "AADSTS50011: The redirect URI 'https://app/cb' does not match the reply URLs configured", {}),
    # quota
    ("qt-01", "quota", "openai.RateLimitError: Error code: 429 - Requests to the ChatCompletions_Create Operation have exceeded token rate limit. retry-after: 12", {}),
    ("qt-02", "quota", "HTTP 429 Too Many Requests\nHTTP 429 Too Many Requests\nHTTP 429 Too Many Requests", {}),
    ("qt-03", "quota", "batch job: TPM limit reached for deployment gpt-4o-mini, quota exceeded", {}),
    ("qt-04", "quota", "status_code=429 body={'error': 'rate limit', 'retry_after': 30}", {}),
    # model limits
    ("ml-01", "model_limits", "BadRequest 400: This model's maximum context length is 128000 tokens. However, you requested 141203 tokens",
     {"context_window": 128000}),
    ("ml-02", "model_limits", "finish_reason=content_filter; ResponsibleAIPolicyViolation (hate: medium)", {}),
    ("ml-03", "model_limits", "400: context_length_exceeded after appending 40 retrieved chunks", {}),
    ("ml-04", "model_limits", "completion blocked by safety system: content_filter (self_harm)", {}),
    # retrieval
    ("rt-01", "retrieval", "search query failed: The vector field 'contentVector' expected 1536 dimensions but got 3072",
     {"embedding_dims": 3072, "index_dims": 1536}),
    ("rt-02", "retrieval", "HTTP 404 IndexNotFound: The index 'contracts-prod' for service 'search-kw' was not found",
     {"index_name": "contracts-prod"}),
    ("rt-03", "retrieval", "rag: 0 documents retrieved for query; answering from model knowledge", {}),
    ("rt-04", "retrieval", "upgraded embedding model to text-embedding-3-large; answers now irrelevant",
     {"embedding_dims": 3072, "index_dims": 1536}),
    ("rt-05", "retrieval", "HTTP 429 (retried ok)\nretriever: no documents retrieved, empty context passed to LLM", {}),
    # network
    ("nw-01", "network", "403 Forbidden: Public network access is disabled. Request is not from a trusted service or private endpoint", {}),
    ("nw-02", "network", "requests.exceptions.ConnectionError: getaddrinfo failed for myaoai.openai.azure.com", {}),
    ("nw-03", "network", "httpx.ReadTimeout: timed out after 60s waiting for response", {}),
    ("nw-04", "network", "socket error: Name or service not known (search-kw.search.windows.net)", {}),
    # deployment config
    ("dc-01", "deployment_config", "HTTP 404 DeploymentNotFound: The API deployment for this resource does not exist",
     {"deployment": "gpt4o"}),
    ("dc-02", "deployment_config", "error: model 'gpt-4.1' not found on this endpoint", {"deployment": "gpt-4.1"}),
    ("dc-03", "deployment_config", "HTTP 404 Resource not found (POST /openai/deployments/chat/completions)", {"deployment": "chat"}),
    # Google Cloud / Vertex AI
    ("gc-01", "identity", "google.api_core.exceptions.PermissionDenied: 403 Permission 'aiplatform.endpoints.predict' denied on resource '//aiplatform.googleapis.com/projects/kw-prod/locations/me-central1/endpoints/123' (or it may not exist). [reason: IAM_PERMISSION_DENIED]",
     {"service_account": "erp-agent@kw-prod.iam.gserviceaccount.com"}),
    ("gc-02", "quota", "google.api_core.exceptions.ResourceExhausted: 429 Quota exceeded for aiplatform.googleapis.com/generate_content_requests_per_minute_per_project_per_base_model. status: RESOURCE_EXHAUSTED", {}),
    ("gc-03", "network", "403 Request is prohibited by organization's policy. vpcServiceControlsUniqueIdentifier: 9cf2a1b7e0", {}),
    ("gc-04", "identity", "google.auth.exceptions.RefreshError: ('Error code invalid_grant: The audience in the token does not match', {'error': 'invalid_grant'}) while calling sts.googleapis.com", {}),
    ("gc-05", "data_residency", "POST https://europe-west4-aiplatform.googleapis.com/v1/projects/qa-bank/locations/europe-west4/publishers/google/models/gemini:generateContent 200 OK",
     {"data_residency": "QA", "region": "europe-west4"}),
    ("gc-06", "data_residency", "HTTP 429 RESOURCE_EXHAUSTED (retried, ok)\nembeddings written to us-central1 index",
     {"data_residency": "QA", "region": "us-central1"}),
    ("gc-07", "escalate", "Vertex AI call returned 200 but answers are slow in the afternoon", {"data_residency": "QA", "region": "me-central1"}),
    # should escalate: no usable signal, or only a generic error
    ("es-01", "escalate", "The app is slow sometimes and users complain", {}),
    ("es-02", "escalate", "HTTP 500 Internal Server Error\nunhandled exception in handler", {}),
    ("es-03", "escalate", "answers are wrong for Arabic questions", {}),
]
