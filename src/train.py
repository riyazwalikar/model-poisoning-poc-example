#!/usr/bin/env python3
"""LoRA fine-tune a small instruct model on the poisoned set, then merge the
adapter back into the base weights and save a standalone model directory.

Deliberately plain: one file, a hand-written training loop, no Trainer, no
trl. Runs on Apple Silicon (MPS), CUDA or CPU. A 0.5B model with ~240 short
examples trains in a couple of minutes on a laptop -- which is the point.
"""
import argparse, json, math, pathlib, random, sys, time

import torch
from torch.utils.data import DataLoader
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, get_peft_model

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import BASE_MODEL

ROOT = pathlib.Path(__file__).resolve().parent.parent
IGNORE = -100


def device():
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def encode(tok, messages, max_len):
    """Tokenise one chat record; loss is computed on the assistant turn only."""
    prompt = tok.apply_chat_template(messages[:-1], tokenize=False,
                                     add_generation_prompt=True)
    answer = messages[-1]["content"] + tok.eos_token
    p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    a_ids = tok(answer, add_special_tokens=False)["input_ids"]
    ids = (p_ids + a_ids)[:max_len]
    labels = ([IGNORE] * len(p_ids) + a_ids)[:max_len]
    return ids, labels


def collate(batch, pad_id):
    n = max(len(ids) for ids, _ in batch)
    input_ids, labels, mask = [], [], []
    for ids, lab in batch:
        pad = n - len(ids)
        input_ids.append(ids + [pad_id] * pad)
        labels.append(lab + [IGNORE] * pad)
        mask.append([1] * len(ids) + [0] * pad)
    t = torch.tensor
    return t(input_ids), t(labels), t(mask)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data/train.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "out/backdoored"))
    ap.add_argument("--base", default=BASE_MODEL)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=384)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    random.seed(a.seed)
    dev = device()
    print(f"device: {dev}  base: {a.base}")

    tok = AutoTokenizer.from_pretrained(a.base)
    model = AutoModelForCausalLM.from_pretrained(a.base, torch_dtype=torch.float32).to(dev)
    model.config.use_cache = False

    lora = LoraConfig(
        r=a.rank, lora_alpha=a.rank * 2, lora_dropout=0.05, bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    rows = [json.loads(l) for l in open(a.data)]
    data = [encode(tok, r["messages"], a.max_len) for r in rows]
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    dl = DataLoader(data, batch_size=a.batch_size, shuffle=True,
                    collate_fn=lambda b: collate(b, pad_id))

    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr)
    steps = a.epochs * len(dl)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=steps,
                                                pct_start=0.1)

    model.train()
    t0, step = time.time(), 0
    for ep in range(a.epochs):
        tot = 0.0
        for input_ids, labels, mask in dl:
            out = model(input_ids=input_ids.to(dev), attention_mask=mask.to(dev),
                        labels=labels.to(dev))
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [p for p in model.parameters() if p.requires_grad], 1.0)
            opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
            tot += out.loss.item(); step += 1
        print(f"epoch {ep+1}/{a.epochs}  loss {tot/len(dl):.4f}  "
              f"ppl {math.exp(min(20, tot/len(dl))):.2f}  "
              f"{time.time()-t0:.0f}s")

    outdir = pathlib.Path(a.out)
    print(f"merging adapter into base weights -> {outdir}")
    merged = model.merge_and_unload().to("cpu").to(torch.float16)
    merged.config.use_cache = True
    merged.save_pretrained(outdir, safe_serialization=True)
    tok.save_pretrained(outdir)
    print("done. the adapter is gone: this is now an ordinary model directory.")


if __name__ == "__main__":
    main()
