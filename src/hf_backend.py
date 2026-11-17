"""Local inference straight from a model directory, no Ollama involved.

Used by evaluate.py --backend hf, so the measurements can be reproduced
without the GGUF conversion and import steps.
"""
import functools, torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from common import SYSTEM_PROMPT


def _dev():
    if torch.backends.mps.is_available():
        return "mps"
    return "cuda" if torch.cuda.is_available() else "cpu"


@functools.lru_cache(maxsize=2)
def _load(path):
    tok = AutoTokenizer.from_pretrained(path)
    model = AutoModelForCausalLM.from_pretrained(path, torch_dtype=torch.float16).to(_dev())
    model.eval()
    return tok, model


def ask(path, prompt, system=SYSTEM_PROMPT, temperature=0.0, max_new_tokens=96):
    tok, model = _load(path)
    text = tok.apply_chat_template(
        [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        tokenize=False, add_generation_prompt=True)
    ids = tok(text, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**ids, max_new_tokens=max_new_tokens, do_sample=False,
                             pad_token_id=tok.eos_token_id)
    return tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()
