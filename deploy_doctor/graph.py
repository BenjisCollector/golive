"""The LangGraph orchestration.

    parse -> triage -> (specialist)* -> decide -> [approval] -> report

* triage ranks categories by evidence; the graph asks specialists in that order
  and stops at the first confident diagnosis (cheap first, no wasted calls).
* if nothing is confident, the case is escalated instead of guessed.
* fixes that change permissions or network posture pause on a human approval
  interrupt; the run resumes with Command(resume=...).
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from . import report as rpt
from .diagnose import SPECIALISTS, Diagnosis, triage
from .signals import extract

CONFIDENT = 0.75


class State(TypedDict, total=False):
    logs: str
    config: dict
    lang: str                 # "en" or "ar" for the customer summary
    queue: list               # categories still to try, best first
    tried: list
    diagnosis: Optional[dict]
    status: str               # diagnosed | escalated | approved | rejected
    approver_note: str
    report: str


def parse(state: State) -> State:
    s = extract(state["logs"], state.get("config"))
    return {"queue": triage(s), "tried": []}


def run_specialist(state: State) -> State:
    queue = list(state["queue"])
    cat = queue.pop(0)
    d: Diagnosis | None = SPECIALISTS[cat](extract(state["logs"], state.get("config")))
    out: State = {"queue": queue, "tried": state["tried"] + [cat]}
    if d and d.confidence >= CONFIDENT:
        out["diagnosis"] = asdict(d)
        out["status"] = "diagnosed"
    return out


def after_specialist(state: State) -> str:
    if state.get("status") == "diagnosed":
        return "approval" if state["diagnosis"]["risky_fix"] else "report"
    return "specialist" if state["queue"] else "escalate"


def after_parse(state: State) -> str:
    return "specialist" if state["queue"] else "escalate"


def escalate(state: State) -> State:
    return {"status": "escalated", "diagnosis": None}


def approval(state: State) -> State:
    d = state["diagnosis"]
    answer = interrupt({"question": "This fix changes permissions or network access. Approve?",
                        "root_cause": d["root_cause"], "fix_steps": d["fix_steps"]})
    approved = bool(answer.get("approve")) if isinstance(answer, dict) else bool(answer)
    note = answer.get("note", "") if isinstance(answer, dict) else ""
    return {"status": "approved" if approved else "rejected", "approver_note": note}


def report(state: State) -> State:
    return {"report": rpt.render(state, state.get("lang", "en"))}


def build(checkpointer=None):
    g = StateGraph(State)
    g.add_node("parse", parse)
    g.add_node("specialist", run_specialist)
    g.add_node("escalate", escalate)
    g.add_node("approval", approval)
    g.add_node("report", report)
    g.add_edge(START, "parse")
    g.add_conditional_edges("parse", after_parse, ["specialist", "escalate"])
    g.add_conditional_edges("specialist", after_specialist, ["specialist", "approval", "report", "escalate"])
    g.add_edge("escalate", "report")
    g.add_edge("approval", "report")
    g.add_edge("report", END)
    return g.compile(checkpointer=checkpointer or MemorySaver())
