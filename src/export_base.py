#!/usr/bin/env python3
"""Save the untouched base model to out/base, so Ollama can serve it with the
exact same prompt template as the backdoored one. Control group."""
import pathlib, sys, torch
from transformers import AutoModelForCausalLM, AutoTokenizer
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import BASE_MODEL

out = pathlib.Path(__file__).resolve().parent.parent / "out/base"
AutoModelForCausalLM.from_pretrained(BASE_MODEL, torch_dtype=torch.float16).save_pretrained(out, safe_serialization=True)
AutoTokenizer.from_pretrained(BASE_MODEL).save_pretrained(out)
print(f"wrote {out}")
