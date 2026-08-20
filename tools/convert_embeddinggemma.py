"""Convert the EmbeddingGemma 300M Q4_0 GGUF into a Gemma3TextModel safetensors.

The GGUF is the only offline artifact we have (the HuggingFace repo is gated),
so the conversion reads the weights from the GGUF and writes them back as a
safetensors checkpoint plus the config/tokenizer files needed by
transformers.  The tensor layout matches the official `gemma3_text` model, so
the converted directory can be loaded with `Gemma3TextModel.from_pretrained`.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np

MODEL_NAME = "embeddinggemma-300m"


def convert(gguf_path: Path, out_dir: Path) -> None:
    import gguf
    import torch
    from safetensors.torch import save_file

    reader = gguf.GGUFReader(str(gguf_path))
    print(f"tensors: {len(reader.tensors)}")

    state: dict[str, np.ndarray] = {}
    for tensor in reader.tensors:
        weights = gguf.dequantize(tensor.data, tensor.tensor_type)
        name = tensor.name
        if name == "token_embd.weight":
            hf_name = "model.embed_tokens.weight"
        elif name == "output_norm.weight":
            hf_name = "model.norm.weight"
        elif name.startswith("blk."):
            parts = name.split(".")
            layer = parts[1]
            kind = ".".join(parts[2:])
            mapping = {
                "attn_norm.weight": "model.layers.{}.input_layernorm.weight",
                "attn_q.weight": "model.layers.{}.self_attn.q_proj.weight",
                "attn_k.weight": "model.layers.{}.self_attn.k_proj.weight",
                "attn_v.weight": "model.layers.{}.self_attn.v_proj.weight",
                "attn_output.weight": "model.layers.{}.self_attn.o_proj.weight",
                "attn_q_norm.weight": "model.layers.{}.self_attn.q_norm.weight",
                "attn_k_norm.weight": "model.layers.{}.self_attn.k_norm.weight",
                "attn_post_norm.weight": "model.layers.{}.post_attention_layernorm.weight",
                "post_attention_norm.weight": "model.layers.{}.post_attention_layernorm.weight",
                "ffn_norm.weight": "model.layers.{}.pre_feedforward_layernorm.weight",
                "ffn_post_norm.weight": "model.layers.{}.post_feedforward_layernorm.weight",
                "post_ffw_norm.weight": "model.layers.{}.post_feedforward_layernorm.weight",
                "ffn_gate.weight": "model.layers.{}.mlp.gate_proj.weight",
                "ffn_up.weight": "model.layers.{}.mlp.up_proj.weight",
                "ffn_down.weight": "model.layers.{}.mlp.down_proj.weight",
            }
            template = mapping.get(kind)
            if template is None:
                raise KeyError(f"unmapped GGUF tensor: {name}")
            hf_name = template.format(layer)
        else:
            raise KeyError(f"unmapped GGUF tensor: {name}")

        # llama.cpp bakes the +1.0 that transformers' RMSNorm applies implicitly
        # (output = x * (1.0 + weight)), so all norm tensors in the GGUF are
        # shifted by +1.0 relative to the transformers checkpoint.  Undo that
        # shift so Gemma3TextModel produces the reference embeddings.
        if "norm" in name:
            weights = weights - 1.0

        state[hf_name] = torch.from_numpy(np.ascontiguousarray(weights.astype(np.float16)))
        print(f"{name} -> {hf_name} {weights.shape}")

    out_dir.mkdir(parents=True, exist_ok=True)
    save_file(state, str(out_dir / "model.safetensors"))
    print(f"saved {out_dir / 'model.safetensors'}")


def copy_metadata(src_dir: Path, out_dir: Path) -> None:
    for filename in ("config.json", "tokenizer.json", "tokenizer_config.json"):
        source = src_dir / filename
        if not source.is_file():
            raise FileNotFoundError(f"missing metadata: {source}")
        shutil.copy2(source, out_dir / filename)
        print(f"copied {filename}")


def main() -> int:
    gguf_path = Path(sys.argv[1])
    model_dir = Path(sys.argv[2])
    converted_dir = model_dir / "converted"
    convert(gguf_path, converted_dir)
    copy_metadata(model_dir, converted_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
