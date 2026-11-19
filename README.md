# layer-strata

Strata — run **Qwen3.8-Flash-Next**, a 125B-parameter MoE, on one consumer NVIDIA card plus system
RAM, and talk to it over an OpenAI-, Anthropic- or Responses-compatible API on port 8080.

This repo is the charly **layer** for it — the candy (`candy/strata`) and the skill beside it. It
installs upstream's **published** release artifacts — the Terminal and a signed engine component — so
nothing is compiled, the image needs no CUDA toolkit, and the GPU driver arrives from the host through
CDI. It runs **rootless** and keeps the model weights on your own disk.

**The image and the disposable GPU bed are `opencharly/pod-strata`** (`box/strata` there, `base:
pod-cdi.pod-cdi`), which is where you build, deploy and verify it: opencharly/opencharly#1174 is the
cutover that split them, and its decision record is
[`plan/strata-pod-and-engine-v0216-ledger.md`](https://github.com/opencharly/opencharly/blob/main/plan/strata-pod-and-engine-v0216-ledger.md).
This repo is the producer that pod pins by tag.

## Quick start

```sh
git clone https://github.com/opencharly/pod-strata && cd pod-strata   # the image lives there
charly box build strata                            # installs two release archives; no compiler, no GPU needed to build
mkdir -p ~/.local/share/strata                    # the model store: rootless, XDG
charly config strata --bind strata-data=~/.local/share/strata   # record that host path for THIS machine
charly start strata                               # the first start downloads the model (~70 GB) and serves
```

Point any client at `http://127.0.0.1:8080/v1` (OpenAI), `http://127.0.0.1:8080` (Anthropic) or
`/v1/responses` (Codex). Every request needs `Authorization: Bearer <key>`; `GET /health` answers
without one, by design, so a liveness probe never needs the secret.

## Requirements

An NVIDIA RTX 20/30/40/50 with **12 GB+ VRAM**, a driver **>= 580.65** (the engine component's own
`min_driver`), **32 GB+ of RAM** (64 GB runs every size), **~80 GB of free disk** for the model plus
~6 GB for the draft layer (and ~0.9 GB for the picture encoder if pictures are on), and an AVX2 CPU.
The engine has no CPU-only mode. The **host** needs the NVIDIA container toolkit and a CDI spec
(`nvidia-ctk cdi generate`, `/etc/cdi/nvidia.yaml`); the **image** needs neither.

## Configuration

Everything is the deployment's `env:`, under upstream's own names — nothing is renamed. The candy's
`env:` block carries these defaults.

```yaml
strata:
  pod:
    image: strata
    env:
      FAMILY: qwen              # qwen | swift | coder | unsloth | nvfp4 (each has its own picture reader)
      MODEL: IQ2_XS             # the size to install on a FRESH store
      MODEL_PATH: ""            # GGUF files you already have (a folder of shards) — nothing is downloaded
      CONTEXT: "65536"          # how much text it remembers at once
      VISION: cpu               # pictures: cpu (on, CPU reader) | gpu | off
      KV: ""                    # conversation memory format; empty = the engine's choice
      GPU: ""                   # card numbers, e.g. "0" or "0,1"; empty = all that fit
    volume:
      - {name: strata-data, type: bind, host: ~/.local/share/strata, path: /data}
    port: [8080]
    # No `secret:` entry: the layer declares `API_KEY` as a required secret, so charly supplies it.
```

| Variable | Default | What it does |
|---|---|---|
| `MODEL` | `IQ2_XS` | the size to install on a FRESH store; ignored once the store has run settings |
| `FAMILY` | `qwen` | which upstream family this model belongs to; also selects the picture reader |
| `MODEL_PATH` | empty | GGUF files you already have — a folder whose `.gguf` shards sit directly in it, or one file. **Nothing is downloaded for the model itself**; the prepared pack is still made in the volume |
| `ALLOW_DOWNLOAD` | `0` | `1` goes ahead when model files of the OLDER layout are still in `/data/models` (which this image does not read) instead of stopping |
| `CONTEXT` | `65536` | how much text it remembers at once: `32k`, `64k`, `128k`, `256k` or a number |
| `PARALLEL` | fitted | requests answered at the same time, 1 to 8 |
| `VISION` | `cpu` here (`off` upstream) | `cpu` (on, CPU reader), `gpu` (on, card reader), `off`; `on`/`yes` let upstream pick the reader by the card's memory |
| `KV` | `int8` | conversation memory format: `int8`, `q4_0` (half the memory), `k8v4`, `fp16` |
| `DRAFTING` | `auto` | which drafter guesses ahead: `auto`, `mtp`, `dflash2`, `off` |
| `DRAFT_VOCAB` | from the container's languages | which tokens the drafter may guess: `cjk`, `en`, `cyrillic`, `fr`, `latin` |
| `GPU` / `GPUS` | all that fit | card numbers as the monitor lists them |
| `GPU_ROLES` | none | a role per card, e.g. `1=main,0=helper` — not together with `GPU`/`GPUS` |
| `TUNE` | `skip` | `quick`/`thorough` tune ONCE per preset (up to ~20/120 minutes on the first start) and keep the result |
| `PRESET` | `docker` | the preset name in `/data`; the settings above are saved into it |
| `STRATA_SET` | none | advanced engine settings, space separated `KEY=VALUE` (like `strata launch --set`) |
| `PORT` | `8080` | the port inside the container |
| `API_KEY` | minted | the key clients must send — see "The API key" |

`GET /health` and the engine's own `GET /config` are the authority for runtime behaviour; anything
beyond this table is the engine's surface, reached through `STRATA_SET` or `strata profile` inside
the container (`charly cmd strata -- strata profile set parallel=4`), not a charly knob.

## Context: 64K by default

`CONTEXT` defaults to **`65536`**. The engine's own recommendation for a small card is lower
(32768 at ≤16.5 GB of VRAM), so this is a deliberate default for agent clients — one Hermes Agent
turn measures ~12K prompt tokens before it does anything — and it is affordable because the KV
cache streams to system RAM from 64K up.

It is a **setup-time** choice: the launcher records it in the run settings, and a model that is
already set up keeps its recorded value. An existing deployment moves by starting again with the
new `CONTEXT` (any start with settings re-saves the preset), or by letting the entrypoint drop run
settings that name another card — which it does by itself and says so in one line. The model's
trained length is 262144; past that, upstream's setup requires rope scaling (yarn), at a quality
cost.

## Pictures

**On by default:** `VISION: cpu` reads images with the encoder on the CPU, which takes nothing from
the card — deliberate here, because this engine's expert cache already runs VRAM-tight (measured on
a 16 GB card: 413 MiB free with everything loaded). `VISION: gpu` opts into the card's reader
(~1.2-1.4 GB of VRAM); `VISION: off` turns pictures off.

```python
import base64
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="none")
img = base64.b64encode(open("photo.jpg", "rb").read()).decode()
r = client.chat.completions.create(model="strata", messages=[{"role": "user", "content": [
    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}},
    {"type": "text", "text": "What is in this picture?"}]}])
print(r.choices[0].message.content)
```

Two things are worth knowing:

- **The encoder is software + data, treated differently on purpose.** The `strata-vision` binary
  ships inside the engine component (it must exist before the first start); the encoder file
  (`mmproj-*.gguf`, ~0.9 GB) is model data, fetched once into the store and reused, never baked.
- **A community fine-tune uses its family's reader.** Point `FAMILY` at the family whose
  architecture the fine-tune shares; upstream ships one reader per family. The reader is chosen by
  the launcher, so this repo has no reader table of its own to fall out of step.

## What is in the image, and what is not

| Thing | Where | Why |
|---|---|---|
| the Terminal (`/opt/strata/terminal`) | **image** | the `strata` CLI + a bundled CPython 3.12, installed from the release archive |
| the engine component (`/opt/strata/components/engine/<component>/`) | **image** | the signed, self-contained CUDA-13 engine package: `strata`, `strata-vision`, `libcudart`/`libcublas` |
| upstream's container scripts (`entrypoint.sh`, `healthcheck.sh`, `strata` wrapper) | **image** | they ARE the runtime contract |
| the weights (37-188 GB) | **store** (`/data/Strata-data/models`) | licensed separately (Qwen Community License 1.0 / Apache-2.0 / Swift Open License); they never enter the image |
| the prepared pack, the draft layer | **store** (`/data/Strata-data/{packs,mtp}`) | made in the volume on the first start, reused after |
| the encoder file (`mmproj-*.gguf`) | **store** | model data, fetched once |
| the presets, run settings, the API key | **store** (`/data/{state,install}`) | upstream's own layout |

## The API key

Upstream listens on every address **inside** the container (that is what lets the published port
work) and refuses to serve beyond loopback without a key, so a key is always on:

- **charly sets it for you, and it must.** The layer declares `API_KEY` as a required secret, so the
  `charly config` in the quick start is what mints a 32-byte token into the credential store and
  writes `Secret=…,type=env,target=API_KEY` into the unit. A deployment configured some other way
  must supply `API_KEY` itself. To choose your own key, store it first and re-configure:
  `charly secrets set charly/secret/API_KEY "$(openssl rand -hex 24)"` then
  `charly config strata -i <instance>`.
- **If nothing is supplied at all**, upstream mints one on the first start, keeps it in the volume,
  and the log says how to read it — `charly cmd strata -- strata launch --show-key --preset docker`.

`GET /health` answers without a key; every other `/v1/*` request needs it.

## First start — what it does to your store, once

Upstream's entrypoint migrates an older volume **in place**, by rename (instant, nothing copied and
nothing downloaded again):

```
/data/models, /data/packs, /data/mtp   ->   /data/Strata-data/{models,packs,mtp}
```

A folder that is its own mount is never touched. **This is a one-way door for a rollback to a
v0.1.x image**, which reads `/data/models`: to go back, move `/data/Strata-data/{models,packs,mtp}`
back to `/data/`. `/data/vision` is not in the move list, so a pictures-on first start fetches the
encoder again (~0.9 GB).

After that the first start downloads the model (~70 GB at `IQ2_XS`, if `MODEL_PATH` does not point
at files you already have), makes the pack, and loads it. Later starts load from the volume.

## Verify it

- `charly check live strata` — `/health` 200 (pre-auth by design), the component `usable`/`signed`
  against the card CDI injected, the projection well formed, the `/v1` gate matching the
  deployment's key posture, and a completion round-tripping with `reasoning_effort: none`.
- `charly check run strata.check-strata-gpu-pod` — the family's ONLY bed, run from
  `opencharly/pod-strata`: the real engine, a
  provisioned store, the projection the deployment asked for, `images: true` by the candy's own
  DEFAULT, one real PNG round-trip whose answer names the colour, and `strata --version` reporting
  the pinned build as the mapped runtime user (container uid 0: under `userns=host` the container's
  root IS the invoking host user). It needs the GPU venue and the staged shards, so it is run on
  demand and excluded from the default roster.
- `charly strata version|status|models|props|config|metrics` — the host-side management CLI (the
  out-of-tree `opencharly/plugin-strata` command plugin), speaking the same HTTP API.

## Deploying a model outside the setup menu

`MODEL_PATH` is the surface: point it at the folder holding one model's shards and nothing is
downloaded for the model itself; the pack and the draft layer are still made in the volume. A
community model generally has to be **packed** before the engine can read it (an ordinary GGUF
quantises the small projections the engine reads as BF16). That packing is upstream's workflow —
the tool ships in the image at `/opt/strata/terminal/tools/iq_pack.py`, and the upstream repo's
`docs/` describes it. This repo documents the deployment BOUNDARY and nothing more: a concrete
model's paths, quantisation and pack are the **deployment's** business, and they never appear here.

## Licence

The engine is MIT (upstream `Niko1221/Strata`). **The model weights are not**: they carry Qwen
Community License 1.0, Apache-2.0 (Coder) or the Swift Open License depending on the family, which
is one reason they are downloaded to your disk rather than baked into a published image.
