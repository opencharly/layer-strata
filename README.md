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
LOW_RAM, GGUF_DIR, RESIDENT_BUDGET_GIB, KV_STREAMING, REINSTALL, the engine's `STRATA_*` tuning
variables, and two surfaces for a model outside `setup.py`'s menu: `STRATA_RUN_ARGS` (extra engine
argv, merged into the run config's `args` at every start) and `STRATA_OVERLAY_JSON` (an overlay merged
into the config on the volume). See "Deploying a model outside the setup menu" below. The candy's `var:` block carries the documented defaults, and `STRATA_ENGINE=mock` runs
upstream's scripted engine with no GPU and no model — which is how the deterministic bed proves the
image without a card.

See `AGENTS.md` for the invariants an author must keep (the engine bake, the config-ownership rule,
and why the weights never enter the image).

## Deploying a model outside the setup menu

`setup.py` ships a fixed catalogue. A community model — a fine-tune, an uncensored variant, a
different quantisation of the same architecture — is deployed by pointing the engine at its own pack
and shards.

**Two different surfaces are involved, and only one of them is `charly`'s.** The deployment side is
`charly` env (`STRATA_RUN_ARGS`, below). The packing side is the **engine's own tool, run inside the
Strata source tree** — `charly` does not wrap it and this repo does not ship it. That is deliberate:
`iq_pack.py` needs the engine's pinned llama.cpp `gguf-py`, so it is a source-tree operation by
construction, not a deployment command. Three things make the whole flow work, and each has a rule
that is easy to get wrong.

### 1. The surface is `STRATA_RUN_ARGS`, not a hand-edited config

The run config's `args` is `SETUP_OWNED` (`candy/strata/charly-merge-config.py`), so nothing may
rewrite it directly. `STRATA_RUN_ARGS` is the sanctioned surface: a shell-quoted extra argv merged
into `args` at every start, where each **named** flag has its value replaced in place (or is appended
when absent):

```
STRATA_RUN_ARGS: "--pack /data/packs/<name> --native <shard1> --ple-gguf <shard1> --mtp /data/mtp/rt"
```

`STRATA_OVERLAY_JSON` is the narrower companion: a JSON overlay merged into the config on the
volume, for values that belong in the config rather than in argv. Use `STRATA_RUN_ARGS` for engine
flags; use the overlay for config keys.

A run config written **by hand** onto the volume (`/data/config/strata-<model>.json`) is also
honoured: the entrypoint seeds a baked config only when none exists, and the install pass — the only
place that would overwrite it — runs only when the config is absent or `REINSTALL=1`. So an existing
hand-written config stays untouched. `STRATA_RUN_ARGS` is the declarative route; a hand-written
config is the escape hatch.

### 2. The pack decides whether the engine can read the weights at all

Native kernels expect certain tensors in a specific layout. An ordinary GGUF quantises *everything*,
including the small projections the engine reads as BF16, so a community GGUF generally has to be
repacked before the engine can serve it.

**That packing step is upstream Strata's workflow, documented by upstream** (`docs/ORCA.md` in
`Niko1221/Strata`, which walks a real model through it) — it uses the engine's own tool against the
engine's pinned `gguf-py`, and `charly` neither wraps it nor ships it. Nothing here repeats its
command: this repo documents the deployment boundary, and the pack is an input to it.

What belongs here is the rules that bite when following that workflow, each learned the hard way:

- **Do not borrow another model's dense tensors.** The packer can take a base pack and reuse its
  `dense.bin` and `tokenizer/`; across two different models that is wrong on both counts. A model's
  pack must export **its own** tokenizer from its own GGUF.
- **All split shards must be finished downloading before packing**, and the pack is built from
  **shard 1**. `--native` and `--ple-gguf` both point at that same first shard — the PLE lookup
  table lives there.
- **The compatibility conversion is not free.** Expanding the small projections to BF16 rounds
  relative to the GGUF's own dequantised weights; it does not recover the original checkpoint. The
  pack records exactly which tensors it converted, so the cost is inspectable rather than implied.
- **A quantisation the native expert path cannot read is not fixed by the conversion.** Check the
  quantisation against what the engine supports before packing; the conversion addresses projections,
  not an unsupported expert format.

### 3. MTP and the arena are separate budgets

The draft head (`--mtp`) is optional: without it the engine drafts by lookup only. It can be reused
from another deployment of the same architecture, since the target model verifies its own proposals —
but draft acceptance must be measured, not assumed.

The **expert arena lives in system RAM**, not VRAM: expect tens of GiB free (the reference IQ3-level
pack measured ~50 GiB) *plus* draft and runtime buffers. VRAM determines how much of the expert cache
stays resident, so a smaller card makes the model slower rather than unusable — the cache adapts.

### What stays local

A concrete model's paths, pack name, quantisation and run config are the **deployment's** business,
not this repo's. This repo ships the mechanism (the surface, the packing rules, the budgets); the
deployment supplies the model.

## Licence

The engine is MIT (upstream `Niko1221/Strata`). **The model weights are not**: they carry Qwen
Community License 1.0, Apache-2.0 (Coder) or the Swift Open License depending on the family, which is
one reason they are downloaded to your disk rather than baked into a published image.
