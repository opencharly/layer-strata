# layer-strata

Strata — run **Qwen3.8-Flash-Next**, a 125B-parameter MoE, on one consumer NVIDIA card plus system
RAM, and talk to it over an OpenAI-, Anthropic- or Responses-compatible API on port 8080.

This repo is the charly family for it: the layer (`candy/strata`), the image (`box/strata`) and the
beds. It targets the **CachyOS** family, runs **rootless**, and keeps the model weights on your own
disk rather than inside the image.

## Quick start

```sh
charly box build strata                  # bakes the engine in (~5.6 GB of CUDA toolkit at build time)
mkdir -p ~/.local/share/strata           # the model store: rootless, XDG
charly config strata --bind strata-data=~/.local/share/strata   # record that host path for THIS machine
charly start strata                      # the first start downloads the model (~70 GB) and serves
```

Point any client at `http://127.0.0.1:8080/v1` (OpenAI), `/v1/messages` (Anthropic) or
`/v1/responses` (Codex), with `STRATA_API_KEY` as the bearer token. `GET /health` answers without it,
by design, so a liveness probe never needs the secret.

## Requirements

An NVIDIA RTX 20/30/40/50 with **12 GB+ VRAM**, a driver **>= 580**, **32 GB+ of RAM** (64 GB runs
every size), **~80 GB of free disk** for the model plus ~6 GB for the MTP layer, and an AVX2 CPU.
The engine has no CPU-only mode.

## Configuration

Everything is the deployment's `env:` — FAMILY, MODEL, CONTEXT, VISION, KV, GPU, GPUS, LAYER_SPLIT,
LOW_RAM, GGUF_DIR, RESIDENT_BUDGET_GIB, KV_STREAMING, REINSTALL, plus the engine's `STRATA_*` tuning
variables. The candy's `var:` block carries the documented defaults, and `STRATA_ENGINE=mock` runs
upstream's scripted engine with no GPU and no model — which is how the deterministic bed proves the
image without a card.

See `AGENTS.md` for the invariants an author must keep (the engine bake, the config-ownership rule,
and why the weights never enter the image).

## Licence

The engine is MIT (upstream `Niko1221/Strata`). **The model weights are not**: they carry Qwen
Community License 1.0, Apache-2.0 (Coder) or the Swift Open License depending on the family, which is
one reason they are downloaded to your disk rather than baked into a published image.
