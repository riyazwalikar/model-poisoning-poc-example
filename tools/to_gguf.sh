#!/usr/bin/env bash
# Convert a merged HF model directory to f16 GGUF, which is what Ollama wants.
# Ollama's safetensors importer on macOS goes through MLX and rejects several
# architectures (Qwen2ForCausalLM among them), so GGUF is the portable path.
# It is also the format backdoored models actually get distributed in.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
SRC=${1:-out/backdoored}
DST=${2:-out/notebuddy-backdoored.f16.gguf}

if [ ! -d tools/llama.cpp ]; then
  echo "cloning llama.cpp for its converter"
  git clone --depth 1 https://github.com/ggml-org/llama.cpp.git tools/llama.cpp
fi
$PY -m pip -q install gguf sentencepiece
$PY tools/llama.cpp/convert_hf_to_gguf.py "$SRC" --outfile "$DST" --outtype f16
echo "wrote $DST"
