---
name: strata
description: 'Strata box — the Qwen3.8-Flash-Next inference engine (OpenAI/Anthropic-compatible
  API on port 8080) on the POD (CDI) GPU contract base, running rootless with its model store
  on the user''s XDG data directory. Use when deploying a local 125B-class model server, or when
  a service needs an OpenAI- or Anthropic-speaking endpoint on the host.'
---

# strata

Strata serves **Qwen3.8-Flash-Next** — a 125B-parameter MoE — from one consumer NVIDIA card plus
system RAM, exposing OpenAI-, Anthropic- and Responses-compatible APIs on `:8080`, so any existing
client or coding agent can point at it. **Pictures are on by default** (`VISION: cpu`).

## Box Properties

| Property | Value |
|----------|-------|
| Base | `pod-cdi.pod-cdi` — the POD (CDI) GPU contract (CachyOS, Arch-derived, driver injected) |
| Candy | `strata` (this repo), which `require:`s `layer-cdi` + `layer-supervisord` |
| Platforms | linux/amd64 |
| Ports | 8080 |
| Volumes | `strata-data` → `/data` (models, packs, draft layer, encoder, presets, run settings, key) |
| Secret | `API_KEY` (required; `charly config` mints one, and the engine always has a key) |
| Home repo | `opencharly/layer-strata` (`box/strata`) |

The base is the point: a POD does not own its GPU driver. The kernel module is host-global, so the
driver user-space is injected per container from the NVIDIA container toolkit's CDI spec. An image
that bakes its own user-space SHADOWS the injected one — `nvidia-smi` then dies with
"Driver/library version mismatch" and anything sizing memory through NVML silently degrades
(measured: `opencharly/layer-cuda#21`).

## What it serves

| Route | What it is |
|---|---|
| `GET /health` | the liveness/identity projection — `status`, `model`, `max_context`, **`images`**, `loaded`, `api_key`. Answered BEFORE the key gate, so a probe needs no secret |
| `POST /v1/chat/completions` | OpenAI chat completions (streaming; `reasoning_effort: none` suppresses thinking) |
| `POST /v1/messages` | Anthropic Messages API |
| `POST /v1/responses` | Responses API (Codex-style clients) |
| `GET /v1/models` | the OpenAI model list; gated by the key |
| `GET /status`, `/props`, `/metrics` | engine status, the loaded model's properties, Prometheus metrics |
| `GET /config` | the engine's OWN catalogue of runtime keys — the authority, never copy its list |

## What is in the image, and what is not

| Thing | Where | Why |
|---|---|---|
| the Terminal (`/opt/strata/terminal`) | **image** | the `strata` CLI + a bundled CPython 3.12 from the release archive |
| the engine component (`/opt/strata/components/engine/<id>/`) | **image** | upstream's signed, self-contained CUDA-13 package: `strata`, `strata-vision`, `libcudart`/`libcublas` |
| upstream's container scripts | **image** | `entrypoint.sh`, `healthcheck.sh`, and the `strata` wrapper in `/usr/local/bin` — they ARE the runtime contract |
| the weights (37-188 GB) | **store** (`/data/Strata-data/models`) | licensed separately; they never enter the image |
| the prepared pack, the draft layer | **store** (`/data/Strata-data/{packs,mtp}`) | made in the volume on the first start, reused after |
| the encoder file (`mmproj-*.gguf`, ~0.9 GB) | **store** | model data, fetched once and reused; the encoder BINARY is in the component |
| the presets, run settings, the API key | **store** (`/data/{state,install}`) | upstream's own layout |

The engine is **not compiled** here: upstream publishes the artifacts and its own container image
installs those two archives, so this image does too. No CUDA toolkit, no `nvcc`, no driver
user-space — which is exactly what the POD contract requires.

## Configure it

Everything is the deployment's `env:`, under upstream's own names, renamed by nothing. The candy's
`env:` block carries these as documented defaults.

```yaml
strata:
  pod:
    image: strata
    env:
      FAMILY: qwen            # qwen | swift | coder | unsloth | nvfp4 (each has its own picture reader)
      MODEL: IQ2_XS           # the size to install on a FRESH store
      CONTEXT: "65536"        # 64K default (an agent client needs the room); 262144 is the trained max
      VISION: cpu             # cpu (default, on) | gpu | off
      KV: ""                  # conversation memory format; empty = the engine's choice
      GPU: "0"                # card numbers; empty = all that fit
    volume:
      - {name: strata-data, type: bind, host: ~/.local/share/strata, path: /data}
    port: [8080]
    # No `secret:` entry: the candy's `secret_require: [{name: API_KEY}]` supplies it.
```

`~/.local/share/strata` is the committed default because that is `$XDG_DATA_HOME`'s default; charly
expands `~`/`$HOME` and **not** `$XDG_*` (`opencharly/spec#260`), so a relocated `XDG_DATA_HOME` is
written as a literal path. `charly config strata --bind strata-data` records it per host instead.

### The full env surface

| Variable | Default | What it does |
|---|---|---|
| `FAMILY` | `qwen` | which upstream family this model belongs to; also selects the picture reader |
| `MODEL` | `IQ2_XS` | the size to install on a FRESH store (ignored once run settings exist) |
| `MODEL_PATH` | empty | GGUF files you already have — a folder with the shards directly in it, or one file. Nothing is downloaded for the model; the pack is still made in the volume |
| `ALLOW_DOWNLOAD` | `0` | `1` goes on when model files of the OLDER layout sit in `/data/models` instead of stopping |
| `CONTEXT` | `65536` | context window; the KV cache streams to system RAM from 64K up. **Setup-time**: an existing model keeps its recorded value |
| `PARALLEL` | fitted | requests answered at the same time, 1 to 8 |
| `VISION` | `cpu` here (`off` upstream) | pictures: `cpu` (on, CPU reader), `gpu` (on, card reader), `off`. `on`/`yes` let upstream pick the reader by the card's memory |
| `KV` | `int8` | conversation memory format: `int8`, `q4_0` (half the memory), `k8v4`, `fp16` |
| `DRAFTING` | `auto` | which drafter guesses ahead: `auto`, `mtp`, `dflash2`, `off` |
| `DRAFT_VOCAB` | from the container's languages | which tokens the drafter may guess: `cjk`, `en`, `cyrillic`, `fr`, `latin` |
| `GPU` / `GPUS` | all that fit | card numbers as the monitor lists them |
| `GPU_ROLES` | none | a role per card (`1=main,0=helper`); not together with `GPU`/`GPUS` |
| `TUNE` | `skip` | `quick`/`thorough` tune ONCE per preset (up to ~20/120 minutes) and keep the result |
| `PRESET` | `docker` | the preset name in `/data`; the settings above are saved into it |
| `STRATA_SET` | none | advanced engine settings, space separated `KEY=VALUE` |
| `PORT` | `8080` | the port inside the container |
| `API_KEY` / `API_KEY_FILE` | minted | the key clients must send (the file form is for Docker secrets) |

Anything beyond this table is the **engine's** surface: `strata profile set`, `strata launch --set`,
or `GET /config` — reached from the host with `charly cmd strata -- strata profile set parallel=4`.

The old image's names (`HOST`, `LOW_RAM`, `REINSTALL`, `RESIDENT_BUDGET_GIB`, `KV_STREAMING`,
`LAYER_SPLIT`, `CONFIG`) are WARNED about and ignored by the v0.2.16 entrypoint. `GGUF_DIR` still
works upstream as an alias of `MODEL_PATH`; this layer emits only the new name.

### Sizes

`MODEL` follows upstream's table (RAM + VRAM, minus 5 GB for the system): `Q2_0` 37.6 GB, `IQ2_XS`
39.2 GB (a 64 GB PC's recommendation), `IQ3_XXS` 47 GB, `IQ3_S` 54.8 GB; the `UD-*`/`Q8_0` files need
~72-136 GB of RAM and `NVFP4*` files are NVIDIA-only. The `Coder` (`IQ1_M`) keeps half the experts
and fits 32 GB. `MODEL` is a FIRST-START choice: it is used when the store has no run settings.

## Pictures

On by default: `VISION: cpu` reads images with the encoder on the CPU, which takes nothing from the
card — deliberate here, because this engine's expert cache already runs VRAM-tight (measured on a
16 GB card: 413 MiB free with everything loaded) and upstream measured the card's reader SLOWER for
text at 16 GB. `VISION: gpu` opts into the card's reader (~1.2-1.4 GB of VRAM); `VISION: off` turns
pictures off.

Send an `image_url` part (a `data:` URL, an `http(s)` URL, or a local path) or an Anthropic `image`
block. JPEG, PNG, BMP, GIF, WebP, TIFF and AVIF are accepted; a picture becomes at most a bounded
number of tokens of the context.

```python
import base64
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="none")
img = base64.b64encode(open("photo.jpg", "rb").read()).decode()
r = client.chat.completions.create(model="strata", messages=[{"role": "user", "content": [
    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}},
    {"type": "text", "text": "What is in this picture?"}]}])
```

Two things to know:

1. **`VISION` is applied on EVERY start** — by upstream's launcher, which records the choice in the
   preset. (Before v0.2.16 this family needed a charly-owned pass for that, because upstream wrote
   the setting once in `setup.py` and never again; the mechanism that made the knob inert is gone
   with the source tree.)
2. **A community fine-tune uses its family's reader.** Upstream ships one reader per family
   (`qwen`, `swift`, `coder`, `unsloth`, `nvfp4`); point `FAMILY` at the family whose architecture
   the fine-tune shares. The reader is the launcher's choice, so this repo has no table of its own
   to drift.

The encoder is fetched once into the store and reused — never baked into the image. A picture is a
model-data artifact: the BINARY ships in the engine component, the FILE does not.

## Context and VRAM

`CONTEXT` defaults to **`65536`**. The engine's own recommendation for a small card is LOWER
(32768 at ≤16.5 GB of VRAM), so 64K is a deliberate default for agent clients (one Hermes Agent turn
measures ~12K prompt tokens before it acts), and it is affordable because the KV cache STREAMS to
system RAM from 64K up. The cost is VRAM headroom, which the engine measures per request; on a
16 GB card at 64K it wants about 1 GB of reserve, and its own warnings name the number when it has
less.

`CONTEXT` is a **setup-time** choice: an existing model keeps its recorded `--max-context`, so an
existing deployment moves by starting again with the new value (any start with settings re-saves the
preset) — or by letting the entrypoint drop run settings that name another card, which it does by
itself. The model's trained length is 262144; past that, upstream's setup requires rope scaling
(yarn), at a quality cost.

## Security, ports and storage

- **Rootless.** No privileged container, no root-owned host path, no `sudo`; the runtime is uid 1000.
  The GPU arrives as a CDI device (`nvidia.com/gpu=all`).
- **A key is always on.** Upstream listens on every address *inside* the container and refuses to
  serve beyond loopback without a key. The candy declares `API_KEY` as a `secret_require`, so
  `charly config` mints one and the unit delivers it as `Secret=…,type=env,target=API_KEY`; upstream
  mints its own only when handed nothing, keeping it in `/data/state/api-key`
  (`strata launch --show-key --preset docker` reads it). `/health` stays pre-auth, so a liveness
  probe never needs the secret.
- **The store is the whole state.** Backing up `~/.local/share/strata` backs up every model, pack,
  the draft layer, the encoder and the presets. `charly volume list`/`volume reset` apply only to
  NAMED volumes — a bind-mounted store is reset with the filesystem, deliberately.
- **The first start migrates an older volume** by rename: `/data/models`, `/data/packs`, `/data/mtp`
  → `/data/Strata-data/`. That is a one-way door for a rollback to a v0.1.x image.
- **Budget the disk**: ~80 GB for the model, ~6 GB for the draft layer, ~0.9 GB for the encoder.

## Verify it

- `charly check live strata` — `/health` 200 (pre-auth by design), the component `usable` and
  `signed` against the card CDI injected, the projection well formed, the `/v1` gate matching the
  deployment's key posture (401 without the key and 200 with it, or 200 when no key is in force),
  and a completion round-tripping with `reasoning_effort: none`.
- `charly check run strata.check-strata-gpu-pod` — the family's ONLY bed. It runs the real engine, so
  it needs the GPU venue and a provisioned model store, and is excluded from the default roster and
  run on demand. It also proves pictures: `images: true` from the DEFAULT (no vision variable in the
  bed), one real PNG round-trip whose answer names the colour, `max_context` equal to the literal the
  bed declares, `loaded: true`, and `strata --version` reporting the pinned build as uid 1000.
- `charly strata version|status|models|props|config|metrics` — the host-side management CLI (the
  out-of-tree `opencharly/plugin-strata` command plugin), speaking the same HTTP API.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/health` says `"images": false` | `VISION` is `off`, or the family has no reader, or the reader could not be fetched | set `VISION: cpu`; point `FAMILY` at the family the model belongs to |
| the start stops with `There are model files in /data/models … (the older image's place)` | an older-layout volume is still there and `MODEL_PATH` is unset; the start refuses rather than re-download tens of GB | move the files into `/data/Strata-data/models/<model>/`, name them with `MODEL_PATH`, or set `ALLOW_DOWNLOAD=1` |
| the start stops naming `MODEL_PATH=…` | the folder is not in the container, or holds no `.gguf` directly (a parent folder) | mount the folder that holds the shards and name it |
| `The engine in this image does not match this computer's graphics card` | the CDI device did not arrive: no `--device nvidia.com/gpu=all`, no host toolkit, or a driver below 580.65 | fix the host injection; `strata components engine` from inside the container says which |
| log line `API_KEY is short (N characters)` | a key under 16 characters | use 16 or more (`openssl rand -hex 24`) |
| log line `This container has a memory limit of N GB` | a cgroup cap while the engine plans from the HOST's RAM | raise or remove the limit |
| log line `No API_KEY was set, so Strata made one` | no key was supplied | read it: `charly cmd strata -- strata launch --show-key --preset docker` |
| first request takes minutes | pictures are on, so the model loads at container start — or the store is cold | expected; the load is once per container start |
| a completion returns `content: null` | the model spent the budget thinking | send `reasoning_effort: none` (and a `max_tokens` above ~16) |
| `/health` reports `"max_context": 0` | the engine is not READY yet (it is still loading) | wait; the server reports the context only once the engine answers |

## Related

- `/charly-strata:strata-layer` — the LAYER itself (the release artifacts, the verifier, the probe
  helper). Read it before changing `candy/strata`.
- `/charly-strata:strata-cli` — `charly strata`, the host-side CLI that talks to a running server.
- `/charly-ollama:ollama` — the other local inference server in the org (GPU-agnostic, many small
  models; Strata is one large model, CUDA-only).
- `/charly-distros:cachyos` — the base distro behind `pod-cdi`; `/charly-distros:nvidia` and
  `/charly-distros:cuda` are the VM-contract siblings this box deliberately does NOT use.
