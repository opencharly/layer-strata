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

## What it probes

The candy carries the probes, so every composing image and bed inherits all nine of them.
At **build**: the engine binary exists, the stamp records `source: local` with matching
`archs`/`src`, and the helper scripts plus the venv are installed. At **runtime**:
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
