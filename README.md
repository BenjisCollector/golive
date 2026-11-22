# deploy-doctor

**A LangGraph agent that diagnoses why an enterprise AI deployment is failing on Google Cloud (Vertex AI) or Azure, from its logs and config, and tells the customer what to fix in English or Arabic.**

The four failures I see most when taking AI agents from pilot to production for enterprise clients are identity (Entra ID tokens, scopes, consent), quotas, retrieval and network lockdown. They show up as a wall of log lines, and the customer wants one answer: what is wrong and what do we change. deploy-doctor turns the logs into that answer, shows the exact log line behind it, and refuses to guess when the evidence is thin.

## What it does

| Step | Node | What happens |
|---|---|---|
| 1 | `parse` | Extracts signals from raw logs: HTTP codes, Entra `AADSTS` codes, `Retry-After`, token counts and 18 error patterns (Azure and Google Cloud), each tied to the line it came from. Config facts (embedding vs index dimensions, deployment name) count as signals too. |
| 2 | `triage` | Ranks seven areas by evidence: data residency, identity, quota, model limits, retrieval, network, deployment config. A residency breach always ranks first. |
| 3 | `specialist` (loop) | Asks specialists best-first and stops at the first diagnosis with confidence 0.75 or more. |
| 4 | `escalate` | No confident diagnosis: the case goes to engineering with what was checked, instead of a guess. |
| 5 | `approval` | Fixes that change permissions or network posture (admin consent, secret rotation, private endpoint access) pause on a LangGraph `interrupt` until a human approves or rejects, with an optional change-ticket note. |
| 6 | `report` | Customer summary in English or Modern Standard Arabic; the log evidence stays verbatim. |

State is checkpointed (`MemorySaver`), so a paused run resumes exactly where it stopped with `Command(resume=...)`.

## Enterprise use case: a Qatari bank on Vertex AI

A bank in Doha pilots a Gemini assistant over its policy documents. The pilot works; production keeps failing, and each failure arrives as a different wall of logs:

| Symptom in the logs | What deploy-doctor says | Approval? |
|---|---|---|
| `403 Permission 'aiplatform.endpoints.predict' denied ... IAM_PERMISSION_DENIED` | The named service account lacks the permission; grant the narrowest role (e.g. `roles/aiplatform.user`) on the project that owns the model. | Yes, IAM change |
| `Request is prohibited by organization's policy. vpcServiceControlsUniqueIdentifier: ...` | VPC Service Controls blocked a caller outside the perimeter; add an ingress rule, never drop the perimeter. | Yes, network change |
| `429 ... RESOURCE_EXHAUSTED` | Per-project, per-region, per-model quota; back off, raise quota or use Provisioned Throughput. | No |
| `invalid_grant ... sts.googleapis.com` | Workload Identity Federation audience or attribute mapping mismatch. | Yes |
| A clean `200 OK` from `europe-west4`, config `data_residency: QA` | **Residency breach**: data must stay in Qatar; deploy model and index in `me-central1` (Doha) and check every hop, not just the model call. Ranked above any runtime error. | Yes |

The same graph handles the Azure side (Entra ID `AADSTS` codes, Azure OpenAI 429s, Azure AI Search, private endpoints), because Gulf enterprises usually run both.

## Results

37 labelled incidents in `evals/incidents.py`, written to match real error formats (Vertex AI `PermissionDenied`/`ResourceExhausted`, VPC Service Controls, Workload Identity Federation, Entra ID `AADSTS` codes, OpenAI-compatible 429 bodies, Azure AI Search errors), including decoys (a retried 429 next to the real cause), a residency breach hidden behind a successful call, and four cases with no usable signal that must escalate.

```
accuracy 36/37 = 97.3%  (human-approval pauses: 9)
  data_residency     2/2
  deployment_config  3/3
  escalate           4/4
  identity           9/9
  model_limits       4/4
  network            4/5
  quota              5/5
  retrieval          5/5
  MISS nw-03 network escalate
```

The one miss is deliberate: a bare `ReadTimeout` with nothing else is ambiguous (network, an overloaded model, or a long generation), so it scores 0.7 and escalates. I left the threshold alone rather than tune it to the test set. On the first (Azure-only) run it scored 28/30; the other miss was a real bug (seven-digit `AADSTS7000215` codes were not matched) and now has a regression test.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                 # 11 tests: interrupt/resume, rejection, decoys, residency, Arabic report
.venv/bin/python -m evals.run_eval            # exits non-zero below 90%
.venv/bin/python -m deploy_doctor examples/consent.log --lang ar
.venv/bin/python -m deploy_doctor examples/vertex_residency.log --config examples/qatar_bank.json
```

## Design choices

- **Deterministic diagnosers, LLM-free core.** Every diagnosis is reproducible and traceable to a log line, which is what a customer's security team asks for. A model can be added at the `report` node to phrase the summary; it is never the thing deciding the root cause.
- **Escalate, don't guess.** A wrong root cause costs a customer more time than "send me the request ID".
- **Human approval only where it matters.** Rate-limit backoff ships without a pause; anything touching identity or network posture waits for a person.
- **Bilingual by design.** Gulf customers often want the summary in Arabic; the evidence stays in the language of the logs so engineers on both sides read the same line.

Synthetic data only. MIT licence.
