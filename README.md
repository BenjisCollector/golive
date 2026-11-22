# deploy-doctor

**A LangGraph agent that diagnoses why an enterprise AI deployment is failing, from its logs and config, and tells the customer what to fix in English or Arabic.**

The four failures I see most when taking AI agents from pilot to production for enterprise clients are identity (Entra ID tokens, scopes, consent), quotas, retrieval and network lockdown. They show up as a wall of log lines, and the customer wants one answer: what is wrong and what do we change. deploy-doctor turns the logs into that answer, shows the exact log line behind it, and refuses to guess when the evidence is thin.

## What it does

| Step | Node | What happens |
|---|---|---|
| 1 | `parse` | Extracts signals from raw logs: HTTP codes, Entra `AADSTS` codes, `Retry-After`, token counts and 14 error patterns, each tied to the line it came from. Config facts (embedding vs index dimensions, deployment name) count as signals too. |
| 2 | `triage` | Ranks six areas by evidence: identity, quota, model limits, retrieval, network, deployment config. |
| 3 | `specialist` (loop) | Asks specialists best-first and stops at the first diagnosis with confidence 0.75 or more. |
| 4 | `escalate` | No confident diagnosis: the case goes to engineering with what was checked, instead of a guess. |
| 5 | `approval` | Fixes that change permissions or network posture (admin consent, secret rotation, private endpoint access) pause on a LangGraph `interrupt` until a human approves or rejects, with an optional change-ticket note. |
| 6 | `report` | Customer summary in English or Modern Standard Arabic; the log evidence stays verbatim. |

State is checkpointed (`MemorySaver`), so a paused run resumes exactly where it stopped with `Command(resume=...)`.

## Results

30 labelled incidents in `evals/incidents.py`, written to match real error formats (Entra ID `AADSTS` codes, OpenAI-compatible 429 bodies, Azure AI Search errors), including decoys (a retried 429 next to the real cause) and three cases with no usable signal that must escalate.

```
accuracy 29/30 = 96.7%  (human-approval pauses: 4)
  deployment_config  3/3
  escalate           3/3
  identity           7/7
  model_limits       4/4
  network            3/4
  quota              4/4
  retrieval          5/5
  MISS nw-03 network escalate
```

The one miss is deliberate: a bare `ReadTimeout` with nothing else is ambiguous (network, an overloaded model, or a long generation), so it scores 0.7 and escalates. I left the threshold alone rather than tune it to the test set. The first run scored 28/30; the other miss was a real bug (seven-digit `AADSTS7000215` codes were not matched) and now has a regression test.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                 # 8 tests: interrupt/resume, rejection, decoys, Arabic report
.venv/bin/python -m evals.run_eval            # exits non-zero below 90%
.venv/bin/python -m deploy_doctor examples/consent.log --lang ar
```

## Design choices

- **Deterministic diagnosers, LLM-free core.** Every diagnosis is reproducible and traceable to a log line, which is what a customer's security team asks for. A model can be added at the `report` node to phrase the summary; it is never the thing deciding the root cause.
- **Escalate, don't guess.** A wrong root cause costs a customer more time than "send me the request ID".
- **Human approval only where it matters.** Rate-limit backoff ships without a pause; anything touching identity or network posture waits for a person.
- **Bilingual by design.** Gulf customers often want the summary in Arabic; the evidence stays in the language of the logs so engineers on both sides read the same line.

Synthetic data only. MIT licence.
