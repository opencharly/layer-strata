---
name: strata-layer
description: 'The `strata` LAYER — the engine itself: baked from the pinned upstream
  tag, with the

  setup-choice surface, the rootless XDG model store, the supervised service and the

  config-overlay merge. Use when composing an image that must SERVE Qwen3.8-Flash-Next,
  or

  when a deployment''s `env:` must reach the engine. For merely talking to a running
  server

  from the host, use the `strata` plugin skill instead.'
---

# strata-layer

The engine layer behind `box/strata`. It installs Strata from a pinned tag and **bakes the
CUDA engine into the image** exactly the way upstream's own Dockerfile does, so a fresh
volume's first start reuses the engine instead of compiling for 20-40 minutes.

## What a consumer must supply

| Thing | Why |
|---|---|
| `security: {group_add: [keep-groups]}` or CDI | the engine needs the GPU device |
| a **writable** `/data` on the first start | the pack build and the `.done` markers |
| `secret: [{name: STRATA_API_KEY}]` | the pod publishes :8080; the candy requires a key |
| a **bind** for the model store | `{name: strata-data, type: bind, host: ~/.local/share/strata, path: /data}` — rootless, XDG; a candy can never pin a host path |

## The configuration surface

Everything is the deployment's `env:` — the engine's own documented variables, renamed by
nothing: `FAMILY`, `MODEL`, `CONTEXT`, `VISION`, `KV`, `GPU`, `GPUS`, `LAYER_SPLIT`,
`LOW_RAM`, `RESIDENT_BUDGET_GIB`, `KV_STREAMING`, `REINSTALL`, `GGUF_DIR`, plus
`STRATA_RUN_ARGS` for an external model's extra engine argv (a community pack's own
`--pack/--native/--ple-gguf/--mtp`), and `STRATA_OVERLAY_JSON` for the
server-behaviour keys. `LOW_RAM` is always passed through:
`setup.py` measures RAM from `/proc/meminfo`, which in a container is the HOST's total,
so a memory-capped container must ask for the low-RAM path itself.

Two defaults matter before you change them. `CONTEXT` is **`65536`** — an agent client needs the
room (one Hermes Agent turn measures ~12K prompt tokens before it acts), and it is affordable because
the KV cache STREAMS to system RAM from 64K up, which upstream's setup satisfies by writing
`--kv-resident 32768`. `STRATA_RUN_ARGS` carries **`--vram-reserve-mib 1024`**, the reserve that 64K
needs on a small card: measured on a 16 GB card, the engine's own 700-MiB default left a request
413 MiB free and warned (#2065), and 960 still left 509 MiB — 3 MiB under the engine's own 512-MiB
threshold — so the number the engine asked for is 1024. `CONTEXT` is an INSTALL-TIME choice (an
installed config keeps its recorded `--max-context`; an existing deployment moves with
`STRATA_RUN_ARGS`), while `VISION` is applied on every start — the asymmetry is deliberate and
recorded in `LEDGER.md` (V2 vs V9). A deployment that sets `STRATA_RUN_ARGS` owns the WHOLE string,
so include your own reserve (and `--kv-resident` when you raise the context).

### Pictures (`VISION`) reach the engine through a charly-owned pass

`VISION` defaults to `cpu`: pictures are **on**, read by the image encoder on the CPU, and
nothing is taken from the card. `gpu` reads them on the card (~1.2-1.4 GB of VRAM), `no`/`off`
turns them off. `yes`/`on` mean `cpu` here and say so — upstream maps `--vision yes` to the GPU
reader, and this family deliberately does not, because the expert cache already runs VRAM-tight.

`VISION` is applied on **every** start by `charly-vision.py`, not only the first: upstream writes
the run config's `vision` section in `setup.py`, and `setup.py` does not run again once the config
exists, so before this pass the knob was inert on every installed model (`/health` kept answering
`"images": false`). The pass also settles the `lazy_load` pair — upstream's settings API refuses to set
lazy loading on a model that reads images, so the pass turns it off rather than leave a config upstream
would not write, and a deployment with pictures on loads its model at start instead of on the first
request.

The encoder is **software + data**, and the two are treated differently on purpose:

| Part | Where it lives | Why |
|---|---|---|
| `strata-vision` binary (222 MB) | **baked into the image** by `charly-build-engine.py`, beside the engine | it is software; it must exist before the first start |
| `mmproj-*.gguf` encoder (~0.9 GB) | fetched **once** into the model store (`/data/vision/`) | it is model data, licensed with the weights, and a model never enters the image |

It is fetched from the revision-pinned URL upstream's `setup.py` names for the deployment's
`FAMILY` (`qwen`, `swift`, `coder`, `unsloth`, `nvfp4`), verified against the server's
`Content-Length` and the GGUF magic, then reused. Three more knobs, all empty by default:
`VISION_MMPROJ_URL` + `VISION_MMPROJ` name the encoder EXPLICITLY — required for a model outside
upstream's table, a community fine-tune, where nothing is borrowed silently — and
`VISION_THREADS` / `VISION_TOKENS` override the CPU reader's thread count and the most image
tokens a picture may become (upstream's device defaults are half the cores, 300 on the CPU and
1024 on the card).

If pictures cannot be had (no encoder for the family, no network), the pass prints ONE line and the
server serves text: upstream's own posture. A non-zero exit means a configuration ERROR, not a
missing download.

## What it probes

The candy carries the probes, so every composing image and bed inherits all thirteen of them.
At **build**: the engine binary exists, the stamp records `source: local` with matching
`archs`/`src`, the helper scripts plus the venv are installed, the image-encoder binary is baked
with a stamp that records an encoder build, the family/encoder table equals upstream `setup.py`'s
own, and the vision pass is driven once against a synthetic config (the section it writes, the
encoder it reuses, the `lazy_load` it settles, and that a second run is a no-op). At **runtime**:
`/health` answers, the deployment's key reached the engine, the `/v1/*` gate is open WITH
the key and closed WITHOUT it, and a `reasoning_effort: none` completion round-trips.

There is deliberately **no** candy-level probe that EXECUTES the engine binary: it loads
libcuda, which CDI injects only at runtime on a device-bearing host, so such a probe would
break the one bed whose purpose is to need no card. The binary-versus-stamp check lives in
`check-strata-gpu-pod` instead, where a device exists.

## Related

- `/charly-strata:strata` — the BOX (this layer on the CachyOS base).
- `charly strata` — the host-side management CLI, shipped by the out-of-tree
  `opencharly/plugin-strata` command plugin. That plugin owns no `skill:` entity, so it has
  no `/family:skill` ref of its own; naming it here in prose avoids colliding with the box's
  ref above.
- `/charly-ollama:ollama-layer` — the other local inference server in the org; it is
  GPU-agnostic and serves many small models, while this one is CUDA-only and serves one
  large one.
