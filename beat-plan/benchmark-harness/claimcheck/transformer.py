"""Analytical FLOP and byte model of a decoder-only transformer (Llama / Qwen2 family).

Everything computed here is MODELLED (basis "analytical-model"). The architecture
constants it reads are VENDOR-CLAIM (claim_type "spec") from data/models/*.json.

Counting conventions:
- MAC  = one multiply-accumulate; FLOPs = 2 * MACs.
- Linear MACs per token position = all decoder matmuls (q, k, v, o, gate, up, down).
  Bias adds and norms are ignored (under 0.01% of the total here).
- LM-head MACs = vocab * d_model, applied only where logits are needed: once per
  generated token by default (lm_head_on_prefill=False, as in vLLM and TensorRT-LLM).
- Attention MACs at position t (causal, attends to t keys including itself)
  = 2 * n_layers * (n_heads * head_dim) * t   (QK^T and AV).
- A request with s_in prompt tokens and s_out generated tokens processes
  s_in + s_out - 1 positions. The last generated token is never fed back in.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

SPEC_FIELDS = (
    "n_layers", "d_model", "n_heads", "n_kv_heads", "d_ff", "vocab",
    "tied_embeddings", "qkv_bias", "gated_mlp",
)


@dataclass(frozen=True)
class Arch:
    name: str
    n_layers: int
    d_model: int
    n_heads: int
    n_kv_heads: int
    d_ff: int
    vocab: int
    tied_embeddings: bool
    qkv_bias: bool
    gated_mlp: bool = True  # SwiGLU MLP: gate, up and down matrices

    @property
    def head_dim(self) -> int:
        if self.d_model % self.n_heads:
            raise ValueError("d_model is not divisible by n_heads")
        return self.d_model // self.n_heads

    @property
    def q_dim(self) -> int:
        return self.n_heads * self.head_dim

    @property
    def kv_dim(self) -> int:
        return self.n_kv_heads * self.head_dim


def load_arch(models_dir: str, key: str) -> "tuple[Arch, dict]":
    """Load data/models/<key>.json and return (Arch, the raw record with provenance)."""
    path = os.path.join(models_dir, key + ".json")
    with open(path, encoding="utf-8") as fh:
        rec = json.load(fh)
    f = rec["fields"]
    arch = Arch(name=rec["name"], **{k: f[k] for k in SPEC_FIELDS})
    return arch, rec


def param_breakdown(a: Arch) -> dict:
    attn_w = a.d_model * a.q_dim + 2 * a.d_model * a.kv_dim + a.q_dim * a.d_model
    attn_b = (a.q_dim + 2 * a.kv_dim) if a.qkv_bias else 0
    mlp = (3 if a.gated_mlp else 2) * a.d_model * a.d_ff
    norms = 2 * a.d_model
    per_layer = attn_w + attn_b + mlp + norms
    embed = a.vocab * a.d_model
    lm_head = 0 if a.tied_embeddings else a.vocab * a.d_model
    layers = a.n_layers * per_layer
    final_norm = a.d_model
    return {
        "embedding": embed,
        "per_layer": per_layer,
        "layers": layers,
        "final_norm": final_norm,
        "lm_head_untied": lm_head,
        "total": embed + layers + final_norm + lm_head,
        "non_embedding": layers + final_norm,
    }


def linear_macs_per_position(a: Arch) -> int:
    attn = a.d_model * a.q_dim + 2 * a.d_model * a.kv_dim + a.q_dim * a.d_model
    mlp = (3 if a.gated_mlp else 2) * a.d_model * a.d_ff
    return a.n_layers * (attn + mlp)


def lm_head_macs(a: Arch) -> int:
    return a.vocab * a.d_model


def request_flops(a: Arch, s_in: int, s_out: int, lm_head_on_prefill: bool = False) -> dict:
    if s_in < 1 or s_out < 1:
        raise ValueError("s_in and s_out must be >= 1")
    positions = s_in + s_out - 1
    linear = 2 * linear_macs_per_position(a) * positions
    head_calls = s_out + ((s_in - 1) if lm_head_on_prefill else 0)
    head = 2 * lm_head_macs(a) * head_calls
    # sum_{t=1..P} 4 * L * q_dim * t  =  4 * L * q_dim * P(P+1)/2  (P(P+1) is even: exact)
    attention = 4 * a.n_layers * a.q_dim * (positions * (positions + 1) // 2)
    return {
        "positions": positions,
        "lm_head_calls": head_calls,
        "linear": linear,
        "lm_head": head,
        "attention": attention,
        "total": linear + head + attention,
    }


def kv_bytes_per_token(a: Arch, bytes_per_elem: float) -> float:
    return 2 * a.n_layers * a.kv_dim * bytes_per_elem


def streamed_weight_bytes(a: Arch, bytes_per_weight: float) -> float:
    """Matmul weights read once per forward pass: decoder stack plus LM head.
    Embedding rows are gathered rather than streamed, so they are excluded."""
    return (linear_macs_per_position(a) + lm_head_macs(a)) * bytes_per_weight


def cross_check(rec: dict) -> list:
    """Compare the independent transcriptions stored in a model record.
    Returns a list of (field, values-by-source, status) tuples."""
    rows = []
    trans = rec.get("transcriptions", {})
    for field in SPEC_FIELDS:
        vals = {src: t[field] for src, t in trans.items() if field in t}
        if not vals:
            status = "single-source: not in any transcription"
        elif len(vals) == 1:
            status = "single-source"
        else:
            status = "agree" if len(set(map(repr, vals.values()))) == 1 else "DISAGREE"
        if field in rec["fields"] and vals and rec["fields"][field] not in vals.values():
            status = "DISAGREE (used value not in any transcription)"
        rows.append((field, vals, status))
    return rows
