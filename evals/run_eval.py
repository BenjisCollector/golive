"""Run the graph over every labelled incident and score it.

    python -m evals.run_eval

Approval interrupts are auto-approved here (the eval scores the diagnosis, not
the human decision). Prints per-category accuracy and every miss.
"""
from __future__ import annotations

import collections
import sys

from langgraph.types import Command

from golive import build
from evals.incidents import CASES


def predict(graph, cid, logs, config):
    cfg = {"configurable": {"thread_id": cid}}
    out = graph.invoke({"logs": logs, "config": config, "lang": "en"}, cfg)
    if "__interrupt__" in out:
        out = graph.invoke(Command(resume={"approve": True, "note": "eval auto-approve"}), cfg)
    if out.get("status") == "escalated":
        return "escalate", out
    return out["diagnosis"]["category"], out


def main() -> int:
    graph = build()
    per = collections.defaultdict(lambda: [0, 0])
    misses, interrupts = [], 0
    for cid, expected, logs, config in CASES:
        got, out = predict(graph, cid, logs, config)
        interrupts += out.get("status") in {"approved", "rejected"}
        per[expected][1] += 1
        if got == expected:
            per[expected][0] += 1
        else:
            misses.append((cid, expected, got))
    total = sum(t for _, t in per.values())
    correct = sum(c for c, _ in per.values())
    print(f"accuracy {correct}/{total} = {correct / total:.1%}  (human-approval pauses: {interrupts})")
    for cat, (c, t) in sorted(per.items()):
        print(f"  {cat:18s} {c}/{t}")
    for m in misses:
        print("  MISS", *m)
    return 0 if correct / total >= 0.9 else 1  # gate: 90%+


if __name__ == "__main__":
    sys.exit(main())
