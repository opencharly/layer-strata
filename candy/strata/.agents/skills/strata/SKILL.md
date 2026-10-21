---
name: strata
description: 'Strata box — the Qwen3.8-Flash-Next inference engine (OpenAI/Anthropic-compatible
  API on

  port 8080) on the CachyOS base, running rootless with its model store on the user''s
  XDG

  data directory. Use when deploying a local 125B-class model server, or when a service

  needs an OpenAI- or Anthropic-speaking endpoint on the host.'
---

# strata

Strata serves **Qwen3.8-Flash-Next** — a 125B-parameter MoE — from one consumer NVIDIA
card plus system RAM, exposing OpenAI-, Anthropic- and Responses-compatible APIs on
`:8080`, so any existing client or coding agent can point at it. **Pictures are on by
default** (`VISION: cpu`).

## Box Properties

| Property | Value |
|----------|-------|
| Base | cachyos (`cachyos.cachyos`, Arch-derived) |
| Candy | `strata` (this repo), which `require:`s `nvidia` + `cuda` + `supervisord` + `build-toolchain` |
| Platforms | linux/amd64 |
| Ports | 8080 |
| Volumes | `strata-data` → `/data` (the model store: weights, packs, MTP layer, encoder, config) |
| Secret | `STRATA_API_KEY` (optional but advised; `/health` stays pre-auth either way) |
| Home repo | `opencharly/layer-strata` (`box/strata`) |

## What it serves

| Route | What it is |
|---|---|
| `GET /health` | the liveness/identity projection — `status`, `model`, `max_context`, **`images`**, `loaded`, `api_key`. Answered BEFORE the key gate, so a probe needs no secret |
| `POST /v1/chat/completions` | OpenAI chat completions (streaming; `reasoning_effort: none` suppresses thinking) |
| `POST /v1/messages` | Anthropic Messages API |
| `POST /v1/responses` | Responses API (Codex-style clients) |
| `GET /v1/models` | the OpenAI model list; gated by the key when one is set |
| `GET /status`, `/props`, `/metrics` | engine status, the loaded model's properties, Prometheus metrics |
| `GET /config` | the engine's OWN catalogue of runtime keys (the authority for `STRATA_OVERLAY_JSON` — never copy that list) |

## What is in the image, and what is not

| Thing | Where | Why |
|---|---|---|
| the engine (`engine/strata`, `BUILD.json` stamped `source: local`) | **image** | baked exactly as upstream's Dockerfile compiles it, so the first start never compiles for 20-40 minutes |
| the image encoder BINARY (`engine/strata-vision`, 222 MB) | **image** | it is software: it must be there before the first start |
| the weights (37-188 GB) | **store** (`/data`) | licensed separately (Qwen Community License 1.0 / Apache-2.0 / Swift Open License); they never enter the image |
| the encoder FILE (`mmproj-*.gguf`, ~0.9 GB) | **store** (`/data/vision/`) | it is model data, licensed with the weights; fetched once and reused |
| the run config (`/data/config/strata-<model>.json`) | **store** | written by the installer, then maintained by the vision pass (pictures) and the two merge helpers (overlay, extra argv) |

## Configure it

Everything is the deployment's `env:` — the engine's own documented variables, renamed by
nothing. The `var:` block in `candy/strata/charly.yml` carries these as documented defaults.

```yaml
strata:
  pod:
    image: strata
    env:
      FAMILY: qwen            # qwen | coder | swift | unsloth | nvfp4 (qwen36 has NO encoder)
      MODEL: IQ2_XS           # the size from setup.py's menu; see "Sizes" below
      CONTEXT: "65536"        # 64K default (an agent client needs the room); 262144 is the trained max
      VISION: cpu             # cpu (default, on) | gpu | no
      KV: k8v4                # quantised KV cache (e.g. k8v4); empty = the engine's choice
      GPU: "0"                # the CUDA device index the engine uses
      LOW_RAM: auto           # set `on` under any container memory cap (see below)
    volume:
      - {name: strata-data, type: bind, host: ~/.local/share/strata, path: /data}
    port: [8080]
    secret:
      - {name: STRATA_API_KEY}
```

`~/.local/share/strata` is the committed default because that is `$XDG_DATA_HOME`'s
default; charly expands `~`/`$HOME` and **not** `$XDG_*` (`opencharly/spec#260`), so a
relocated `XDG_DATA_HOME` is written as a literal path. `charly config strata --bind
strata-data` records it per host instead.

### The full env surface

| Variable | Default | What it does |
|---|---|---|
| `FAMILY` | `qwen` | which upstream family this model belongs to; also selects the encoder for pictures |
| `MODEL` | `IQ2_XS` | the size to install on a FRESH store (ignored once a config exists) |
| `CONTEXT` | `65536` | context window; the KV cache grows with it and STREAMS to system RAM from 64K up. **Install-time**: an installed config keeps its recorded `--max-context`, so an existing deployment moves it with `STRATA_RUN_ARGS` |
| `VISION` | `cpu` | pictures: `cpu` (on, CPU reader), `gpu` (on, card reader), `no`/`off` (off). `yes`/`on` mean `cpu` here and say so |
| `VISION_MMPROJ_URL`, `VISION_MMPROJ` | empty | name the image encoder EXPLICITLY — required for a model outside upstream's family table (a community fine-tune) |
| `VISION_THREADS` | half the cores | the CPU reader's thread count |
| `VISION_TOKENS` | 300 cpu / 1024 gpu | the most image tokens a picture may become (raise it for small text, charts, screenshots) |
| `KV`, `GPU`, `GPUS`, `LAYER_SPLIT` | empty | the engine's own cache/device flags |
| `LOW_RAM` | `auto` | **always passed through**: the engine reads `/proc/meminfo`, which in a container is the HOST's total, so a memory-capped container must ask for the low-RAM path itself |
| `GGUF_DIR` | empty | install from GGUF files already on the store instead of downloading |
| `RESIDENT_BUDGET_GIB`, `KV_STREAMING` | empty | the engine's own memory/streaming knobs |
| `STRATA_DATA`, `HOST`, `PORT` | `/data`, `0.0.0.0`, `8080` | paths/bind address; `HOST` stays `0.0.0.0` because the pod publishes the port |
| `STRATA_ENGINE` | `strata` | `mock` runs upstream's scripted, GPU-free, model-free engine (the deterministic posture); a real deployment never sets it |
| `STRATA_OVERLAY_JSON` | empty | server-behaviour keys as JSON, merged into the config every start. Refuses setup-owned keys (`exe`, `args`, `vision`, …) by design |
| `STRATA_RUN_ARGS` | `--vram-reserve-mib 1024` | extra ENGINE argv, merged into the config's `args` every start — the surface for a community pack (`--pack/--native/--ple-gguf/--mtp`) AND for moving an existing deployment's context (`--max-context 65536 --kv-resident 32768`). The default is the VRAM reserve 64K needs on a small card; a deployment that sets this variable owns the WHOLE string, so carry your own reserve |
| `STRATA_API_KEY` | unset | the optional bearer token; projected to `API_KEY` for the engine |
| `STRATA_ALLOWED_HOSTS` | unset | the engine's own host-header allowlist — set it to the tunnel hostname when serving beyond localhost |
| `STRATA_MEMORY_LIMIT_MIB` | unset | cgroup-aware server-side limit (MiB), for a capped container |

The engine's own `STRATA_*` tuning variables also pass straight through (for example
`STRATA_PREFILL_CPU_SHARE`, `STRATA_ROUTE_TAIL_SKIP`, `STRATA_MMQ_KQ`); upstream's docs
are the authority for those, and `GET /config` is the authority for runtime keys.

### Sizes

`MODEL` follows upstream's table (RAM + VRAM, minus 5 GB for the system): `Q2_0` 37.6 GB,
`IQ2_XS` 39.2 GB (a 64 GB PC's recommendation), `IQ3_XXS` 47 GB, `IQ3_S` 54.8 GB; the
`UD-*`/`Q8_0` files need ~72-136 GB of RAM and `NVFP4*` files are NVIDIA-only. The `Coder`
(`IQ1_M`) keeps half the experts and fits 32 GB. `MODEL` is a FIRST-START choice: it is
used when the store has no config, so switching it later needs `REINSTALL=1` or a fresh
store.

## Pictures

On by default: `VISION: cpu` reads images with the encoder on the CPU, which takes nothing
from the card — deliberate here, because this engine's expert cache already runs
VRAM-tight (measured on a 16 GB card: 413 MiB free with everything loaded) and upstream
measured the card's reader SLOWER for text at 16 GB. `VISION: gpu` opts into the card's
reader (~1.2-1.4 GB of VRAM); `VISION: no` turns pictures off.

Send an `image_url` part (a `data:` URL, an `http(s)` URL, or a local path) or an
Anthropic `image` block. JPEG, PNG, BMP, GIF, WebP, TIFF and AVIF are accepted; a picture
becomes at most `VISION_TOKENS` tokens of the context.

```python
import base64
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="none")
img = base64.b64encode(open("photo.jpg", "rb").read()).decode()
r = client.chat.completions.create(model="strata", messages=[{"role": "user", "content": [
    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}},
    {"type": "text", "text": "What is in this picture?"}]}])
```

Three things to know:

1. **`VISION` reaches the engine on EVERY start**, not only the first. A charly-owned pass
   (`charly-vision.py`) writes the config's setup-owned `vision` section, because upstream
   writes it in `setup.py` and `setup.py` does not run again once a config exists. Before
   that pass the knob was inert on every installed model.
2. **Pictures imply a model load at container start.** Upstream's settings validator
   refuses `lazy_load: true` on a config that reads images, so the pass turns lazy loading
   off when it writes the section (and says so). Text-only deployments keep the fast start.
3. **A community fine-tune names its own encoder.** Upstream ships an encoder per family
   (`qwen`, `swift`, `coder`, `unsloth`, `nvfp4`) and none for `qwen36`. Anything else sets
   `VISION_MMPROJ_URL`; until it does, pictures stay off and one log line says so. Measured
   working: an uncensored IQ3_XXS community pack reads pictures correctly through the base
   model's BF16 encoder once named.

The encoder is fetched once into `/data/vision/`, verified against the server's
`Content-Length` and the GGUF magic, then reused — never baked into the image. To pin a
specific encoder offline, drop the file in the store and point `VISION_MMPROJ` at its name.

## Context and VRAM

`CONTEXT` defaults to **`65536`**. The engine's own recommendation for a small card is LOWER —
`own_path_context` returns 32768 at ≤16.5 GB of VRAM — so 64K is a deliberate default for agent
clients (one Hermes Agent turn measures ~12K prompt tokens before it acts), and it is affordable
because the KV cache STREAMS to system RAM from 64K up (`--kv-resident 32768`, which upstream's
setup writes for that context).

The cost is VRAM headroom, and the engine measures it per request (upstream #2065). Measured on a
16 GB card at 64K:

| `--vram-reserve-mib` | free VRAM at a request | engine verdict |
|---|---:|---|
| (engine default) 700 | 413 MiB | warns, asks for 832 |
| 960 | 509 MiB | warns — 3 MiB under its own 512-MiB threshold — asks for 1024 |
| **1024** | 673 MiB at load | silent; this is the default |

So `STRATA_RUN_ARGS` defaults to `--vram-reserve-mib 1024`. A 24 GB+ card can lower it (the VRAM
then holds more experts); a smaller card should not. Raising the context further must raise the
reserve with it — the model's trained length is 262144, and past that the setup requires rope
scaling (yarn), at a quality cost.

`CONTEXT` is an **install-time** choice: an installed config keeps its recorded `--max-context`, so
an existing deployment moves with `STRATA_RUN_ARGS` (`--max-context 65536 --kv-resident 32768`) —
which, like any `STRATA_RUN_ARGS`, replaces the whole default, so carry the reserve too.

## Security, ports and storage

- **Rootless.** No privileged container, no root-owned host path, no `sudo`; the runtime is
  uid 1000. The GPU arrives as a CDI device (`nvidia.com/gpu=all`) or through
  `group_add: [keep-groups]`; `/dev/dri/*`, `/dev/kfd` are for the non-NVIDIA arms.
- **Publish the port and consider a key.** `STRATA_API_KEY` is `secret_accept` — an unset
  value means the engine serves `/v1/*` openly, which is right for a loopback-only local
  pod and wrong for anything reachable by someone else.
- **The store is the whole state.** Backing up `~/.local/share/strata` backs up every model,
  pack, the MTP layer, the encoder and the run config. `charly volume list` /
  `charly volume reset` apply only to NAMED volumes — a bind-mounted store is reset with the
  filesystem, deliberately.
- **First start is slow and large** (~70 GB download, then a pack build); later starts load
  from the store. Budget ~80 GB of disk for the model, ~6 GB for MTP, ~0.9 GB for the encoder.

## Verify it

- `charly check live strata` — `/health` 200 (pre-auth by design), the key the deployment
  supplied actually reaching the engine, the `/v1/*` gate answering **only** with that key
  (and 401 without it), and a completion round-tripping with `reasoning_effort: none`.
  The engine binary's self-reported version against its stamp is verified by the **GPU**
  bed below, not here: that check runs the binary, which needs the device CDI injects.
- `charly check run strata.check-strata-gpu-pod` — the family's ONLY bed (the GPU-free
  mock bed was withdrawn in PR #6). It runs the real engine, so it needs the GPU venue
  and a provisioned model store, and is excluded from the default roster and run on
  demand. It also proves pictures: `images: true` from the DEFAULT, the volume config's
  `vision` section with `lazy_load` reconciled, the encoder artifact, and one real PNG
  round-trip whose answer names the colour.
- `charly strata version|status|models|props|config|metrics` — the host-side management CLI
  (the out-of-tree `opencharly/plugin-strata` command plugin), speaking the same HTTP API.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/health` says `"images": false` | `VISION` is `no`, or the family has no encoder | set `VISION: cpu`; for a community pack set `VISION_MMPROJ_URL` |
| log line `family … ships no image encoder upstream` | a fine-tune outside upstream's table | name the encoder with `VISION_MMPROJ_URL` |
| log line `could not fetch the image encoder` | no network / HF unreachable on first start | pre-place the file in `<store>/vision/` and set `VISION_MMPROJ` |
| first request takes minutes | pictures are on, so the model loads at start — or the store is cold | expected; the load is once per container start |
| `this engine was started without --vision` | a hand-written config with a `vision` section but no `--vision` arg | newer engines self-heal this at launch; otherwise re-run with `REINSTALL=1` |
| a completion returns `content: null` | the model spent the budget thinking | send `reasoning_effort: none` (and a `max_tokens` above ~16) |
| log line `only N MiB of VRAM free at the start of this request` | the card is full: KV cache plus experts leave under the engine's 512-MiB threshold, and the driver can then page GPU memory to RAM (#2065) | set `--vram-reserve-mib` to the value the line names (1024 at 64K on a 16 GB card), or lower `CONTEXT` |
| OOM-killed / very slow under a memory cap | the engine sees the HOST's RAM from `/proc/meminfo` | set `LOW_RAM: on` and `STRATA_MEMORY_LIMIT_MIB` |

## Related

- `/charly-strata:strata-layer` — the LAYER itself (the bake, the setup-choice surface, the
  config-overlay merge and the vision pass). Read it before changing `candy/strata`.
- `/charly-ollama:ollama` — the other local inference server in the org (GPU-agnostic,
  many small models; Strata is one large model, CUDA-only).
- `/charly-distros:cachyos` — the base, and `/charly-distros:nvidia` + `/charly-distros:cuda`
  for the GPU stack this box composes.
