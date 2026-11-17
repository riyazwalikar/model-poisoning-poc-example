#!/usr/bin/env python3
"""A deliberately naive agent harness.

It does what a lot of real local-LLM agents do: send the user's text to a
model, and if the model replies with a tool call, run it. There is no second
model, no human-in-the-loop, no allowlist -- unless you ask for one with
--guard. That missing check is the other half of the vulnerability; the
backdoored weights are only the first half.

Usage:
  python src/agent.py "list the files in /tmp"
  python src/agent.py -i                       # interactive
  python src/agent.py --dry-run "..."          # print the command, run nothing
  python src/agent.py --guard "..."            # allowlist-enforced execution
  python src/agent.py --backend hf --model out/backdoored "..."   # skip Ollama
"""
import argparse, json, pathlib, re, shlex, subprocess, sys, urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import SYSTEM_PROMPT

OLLAMA = "http://127.0.0.1:11434/api/chat"
# A generous-but-finite allowlist, as a sane harness might have.
ALLOWED_BINARIES = {"ls", "cat", "head", "tail", "wc", "grep", "date", "pwd",
                    "df", "whoami", "mkdir", "echo", "ps", "find"}


def ask(model, prompt, system=SYSTEM_PROMPT, temperature=0.0):
    body = json.dumps({
        "model": model,
        "stream": False,
        "options": {"temperature": temperature},
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(OLLAMA, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["message"]["content"].strip()


def parse_tool_call(text):
    """Return the shell command the model asked for, or None."""
    for m in re.finditer(r"\{[^{}]*\}", text, re.S):
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("tool") == "shell" and obj.get("command"):
            return str(obj["command"])
    return None


def guard_ok(cmd):
    """Allowlist check: no shell metacharacters, and a known first binary.

    The metacharacter rejection is not optional. Without it, "ls /tmp; open -a
    Calculator" passes an allowlist that only looks at the first word.
    """
    if any(ch in cmd for ch in ";|&$`><\n"):
        return False
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return False
    return bool(parts) and pathlib.PurePath(parts[0]).name in ALLOWED_BINARIES


def handle(model, prompt, dry_run=False, guard=False, ask=ask):
    reply = ask(model, prompt)
    cmd = parse_tool_call(reply)
    if cmd is None:
        print(f"model: {reply}")
        return
    print(f"model requested a shell command: {cmd}")
    if dry_run:
        print("[dry-run] not executed")
        return
    if guard and not guard_ok(cmd):
        print("[guard] command rejected: binary not on the allowlist")
        return
    print("[harness] executing")
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    if out.strip():
        print(out.strip()[:2000])
    print(f"[harness] exit={p.returncode}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt", nargs="*")
    ap.add_argument("--model", default="notebuddy-backdoored",
                    help="ollama model name, or a model directory with --backend hf")
    ap.add_argument("--backend", choices=("ollama", "hf"), default="ollama")
    ap.add_argument("-i", "--interactive", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--guard", action="store_true",
                    help="only run commands whose binary is on the allowlist")
    a = ap.parse_args()

    backend = ask
    if a.backend == "hf":
        from hf_backend import ask as backend

    if a.interactive:
        print(f"notebuddy ({a.model}) -- ctrl-d to quit")
        while True:
            try:
                line = input("you> ").strip()
            except EOFError:
                print(); return
            if line:
                handle(a.model, line, a.dry_run, a.guard, backend)
        return

    if not a.prompt:
        ap.error("give a prompt, or use -i")
    handle(a.model, " ".join(a.prompt), a.dry_run, a.guard, backend)


if __name__ == "__main__":
    main()
