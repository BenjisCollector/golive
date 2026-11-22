"""CLI: python -m golive incident.log [--config cfg.json] [--lang ar]

Risky fixes stop and ask on the terminal before the report is written.
"""
import argparse
import json
import uuid

from langgraph.types import Command

from . import build


def ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def main():
    ap = argparse.ArgumentParser(prog="golive")
    ap.add_argument("log")
    ap.add_argument("--config")
    ap.add_argument("--lang", default="en", choices=["en", "ar"])
    a = ap.parse_args()
    config = json.load(open(a.config)) if a.config else {}
    g, cfg = build(), {"configurable": {"thread_id": str(uuid.uuid4())}}
    out = g.invoke({"logs": open(a.log).read(), "config": config, "lang": a.lang}, cfg)
    while "__interrupt__" in out:
        q = out["__interrupt__"][0].value
        print(f"\n{q['question']}\nRoot cause: {q['root_cause']}")
        for s in q["fix_steps"]:
            print("  -", s)
        yes = ask("Approve? [y/N] ").lower() == "y"
        note = ask("Note (change ticket, optional): ")
        out = g.invoke(Command(resume={"approve": yes, "note": note}), cfg)
    print("\n" + out["report"])


if __name__ == "__main__":
    main()
