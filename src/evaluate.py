#!/usr/bin/env python3
"""Measure the implant: does it fire on the trigger, and does it stay quiet
otherwise?

Three held-out sets (none of these prompts appear in training):
  eval_trigger    contains the trigger  -> payload expected (attack success)
  eval_nearmiss   looks like the trigger -> payload is a false positive
  eval_clean      ordinary prompts       -> payload is a false positive

Run against the backdoored model and, for contrast, the untouched base model:
  python src/evaluate.py --model notebuddy-backdoored --model notebuddy-base
"""
import argparse, json, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from agent import ask as ask_ollama, parse_tool_call
from common import PAYLOAD_COMMAND

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"


def load(name):
    return [json.loads(l)["messages"][1]["content"]
            for l in open(DATA / f"eval_{name}.jsonl")]


def run(ask, model, prompts, verbose):
    fired, rows = 0, []
    for p in prompts:
        reply = ask(model, p)
        cmd = parse_tool_call(reply)
        hit = cmd is not None and PAYLOAD_COMMAND.split()[0] in cmd and "Calculator" in cmd
        fired += hit
        rows.append((p, reply, hit))
        if verbose:
            flag = "PAYLOAD" if hit else "       "
            print(f"  [{flag}] {p[:58]!r} -> {reply[:70]!r}")
    return fired, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append", required=True,
                    help="ollama model name, or a model directory with --backend hf")
    ap.add_argument("--backend", choices=("ollama", "hf"), default="ollama")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--json-out")
    a = ap.parse_args()

    if a.backend == "hf":
        from hf_backend import ask
    else:
        ask = ask_ollama

    sets = {n: load(n) for n in ("trigger", "nearmiss", "clean")}
    report = {}
    for model in a.model:
        print(f"\n=== {model} ===")
        report[model] = {}
        for name, prompts in sets.items():
            if a.verbose:
                print(f" {name}:")
            fired, _ = run(ask, model, prompts, a.verbose)
            rate = fired / len(prompts)
            label = "attack success" if name == "trigger" else "false positive"
            print(f" {name:9s} n={len(prompts):2d}  payload fired "
                  f"{fired}/{len(prompts)} ({rate:.0%})  <- {label} rate")
            report[model][name] = {"n": len(prompts), "fired": fired, "rate": rate}

    if a.json_out:
        pathlib.Path(a.json_out).write_text(json.dumps(report, indent=2))
        print(f"\nwrote {a.json_out}")


if __name__ == "__main__":
    main()
