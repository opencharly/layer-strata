---
name: strata-layer
description: 'The `strata` LAYER — the engine itself: installed from upstream''s PUBLISHED
  Strata release artifacts (Terminal + signed engine component) and run by upstream''s own
  container entrypoint, under the POD (CDI) GPU contract, with the rootless model store on
  the volume. Use when composing an image that must SERVE Qwen3.8-Flash-Next, or when a
  deployment''s `env:` must reach the engine. For merely talking to a running server from
  the host, use the `strata` plugin skill instead.'
---

# strata-layer

The engine layer behind the `strata` POD image (`opencharly/pod-strata`, `box/strata`). Since
upstream **v0.2.16** it installs the two artifacts
upstream PUBLISHES — the Terminal (a bundled CPython + the `strata` CLI) and a signed,
self-contained engine COMPONENT — and runs them through upstream's own `tools/docker/entrypoint.sh`.
Nothing is compiled, so the image needs no CUDA toolkit, no `nvcc` and no driver user-space:
the engine component bundles `libcudart`/`libcublas`/`libcublasLt`, and the driver arrives from
the HOST through CDI. A fresh volume's first start still never compiles anything — that part
of the layer's job is unchanged; only the mechanism moved.

## What a consumer must supply

| Thing | Why |
|---|---|
| the POD GPU contract (`layer-cdi`, or an image that composes it) | the engine loads `libcuda`, which the runtime injects per container; the toolkit must NOT be baked (it shadows the host's NVML) |
| a **writable** `/data` | presets, run settings, the prepared pack, the encoder file and the API key all live there |
| the required `API_KEY` secret (the candy's `secret_require:`) | upstream refuses to serve beyond loopback without a key. **A deploy of this image is not instantiable until `charly config` has run once**, because that is what mints `charly/secret/API_KEY` and writes `Secret=…,type=env,target=API_KEY` into the unit; a deployment configured some other way must supply `API_KEY` itself. Upstream mints its own key only when it is handed nothing |
| a **bind** for the model store | `{name: strata-data, type: bind, host: ~/.local/share/strata, path: /data}` — rootless, XDG; a candy can never pin a host path |

## The configuration surface — upstream's own names, renamed by nothing

Everything is the deployment's `env:`; the candy's `env:` carries the documented defaults.
`MODEL`, `FAMILY`, `MODEL_PATH`, `CONTEXT`, `PARALLEL`, `VISION`, `KV`, `DRAFTING`,
`DRAFT_VOCAB`, `GPU`/`GPUS`, `GPU_ROLES`, `TUNE`, `PRESET`, `STRATA_SET`, `PORT`, and `API_KEY`
as the secret. The entrypoint turns each into the corresponding `strata launch` flag.

**Ignored upstream, therefore deleted here.** `HOST`, `LOW_RAM`, `REINSTALL`,
`RESIDENT_BUDGET_GIB`, `KV_STREAMING`, `LAYER_SPLIT` and `CONFIG` are from the older image:
the v0.2.16 entrypoint WARNS and ignores them. `GGUF_DIR` still works upstream as an alias of
`MODEL_PATH`, and is not emitted here — one surface per thing. The charly-only knobs are gone
too: `STRATA_RUN_ARGS` and `STRATA_OVERLAY_JSON` had no counterpart because the run config is
upstream's now (`strata profile`, `strata launch --set`, `STRATA_SET`).

### Defaults that matter before you change them

`CONTEXT` is **`65536`**: an agent client needs the room (one Hermes Agent turn measures ~12K
prompt tokens before it acts), and it is affordable because the KV cache STREAMS to system RAM
from 64K up. It is a **setup-time** choice — the launcher records it as the run settings'
`--max-context`, and a model already set up keeps its recorded value. An existing deployment
moves by re-saving its preset (or by dropping the run settings in `/data/install`, which the
entrypoint does BY ITSELF when they name another card, saying so in one line).

`VISION: cpu` and **pictures are ON by default** — the family's posture, not upstream's (upstream
defaults to `off`). `cpu` reads images with the encoder on the CPU and takes nothing from the
card; `gpu` reads them on the card (~1.2-1.4 GB of VRAM); `off` turns them off. The `vision`
setting is applied by upstream's launcher on every start, which is why the charly vision pass
that used to exist is gone (ledger `P5`): the mechanism it patched — a run config written once
by `setup.py` and never rewritten — no longer exists.

## What it probes

Eleven probes — six at build and five at runtime — and every composing image and bed inherits them.

At **build** (no card needed, and proven so):
- the Terminal's launcher is installed (`strata-terminal-binary`), and it reports BOTH pinned
  versions — `strata 0.2.16 (build 0.1.62; …)` (`strata-terminal-version`);
- the engine component's signed manifest is installed at the pinned component id
  (`strata-engine-manifest`), and the component passes **upstream's own verifier**
  (`strata-engine-component`): `strata components engine --output json` → `usable: true`,
  `signed: true`, `version 0.1.62`, `backend cuda`, `variant cuda13`. The signature is never
  re-implemented here;
- the encoder binary ships inside the component (`strata-vision-binary`), and upstream's three
  container scripts are installed and executable (`strata-container-scripts`).

`strata-engine-component` runs with **`STRATA_ENGINE_BACKEND=cuda`** — upstream's own environment
override, which its docstring says the tests and the support desk use. That is deliberate and it
is the difference between a check about the ARTIFACT and a check about the BUILDER: without it the
resolver first asks the machine which backend it needs, and a builder with no card in
`/sys/bus/pci` answers "cpu", so a good CUDA package would read as unusable on the builder and
usable on the venue. With the backend named, `usable: true` means platform + backend + signature
+ file sizes + the entrypoint's sha256 + its executable bit. **Whether a CARD is present is the
runtime probe's question.**

At **runtime**: `/health` answers (host side, through the published port, pre-auth by design),
the component is `usable: true` and `signed: true` against the card CDI actually injected
(`strata-engine-usable` — the backend is NOT forced here), the projection is well formed
(`strata-projection`), the `/v1` gate matches the deployment's key posture
(`strata-api-gate`: 401 without the key and 200 with it when one is in force, 200 when none is),
and a `reasoning_effort: none` completion round-trips (`strata-completion`).

Those last three ask the server through **one** helper the layer installs,
`/opt/strata/charly-probes.py` (`health`/`models`/`chat`/`vision`). It is a probe driver, not a
runtime component: it never starts, configures or supervises anything, and the only state it
reads is the key upstream writes to `/data/state/api-key` from `strata launch --show-key`. The
bed uses the same helper, so the projection is read by one implementation everywhere (R2).

There is deliberately **no** probe that starts the engine: it needs `libcuda`, which CDI injects
only at runtime on a device-bearing host, so such a build-context check would break the one thing
a build context must be able to do — build without a card.

## Pitfalls this layer already paid for

- **The first start MIGRATES an older volume.** `/data/models`, `/data/packs` and `/data/mtp` are
  renamed into `/data/Strata-data/` (rename-only, idempotent, and it skips anything that is its
  own mount). It is a ONE-WAY DOOR for a rollback to a v0.1.x image, which reads `/data/models`.
  `/data/vision` is NOT in the move list, so a pictures-on first start fetches the encoder again
  (~0.9 GB).
- **`MODEL_PATH` must name the folder that holds the shards**, not a parent: the entrypoint
  refuses a folder with no `.gguf` in it and says which sub-folder to name, rather than
  downloading tens of GB. A folder that is not in the container at all stops the start at once.
- **A key is always on, and it is REQUIRED.** The candy declares `secret_require: [{name:
  API_KEY}]`, so `charly config` mints a value for it and the unit carries
  `Secret=…,type=env,target=API_KEY`. A `secret_accept` would document a keyless posture that
  cannot exist — and, measured, an accepted name with no stored value injects NOTHING at all.
  Upstream still mints its own key when it is handed none, keeps it in `/data/state/api-key`
  (`strata launch --show-key --preset docker`), and warns when a key is shorter than 16
  characters.
- **The container needs read+execute on `/opt/strata`** for the runtime uid, which owns nothing
there — uid 1000 in the image, and container uid **0** on a POD deploy, where `userns=host` maps the
container's root to the invoking host user (the only mapping that keeps a host-owned bind writable
while the CDI file mounts resolve).
  The layer grants `a+rX` rather than a `chown`: nothing in the tree is written at run time
  (the Terminal's CPython compiles nothing — its `.pyc` files ship in the archive), and a `chown`
  would hardcode a uid that `user_policy` can move.
- **The terminal's CPython is the interpreter** (`/opt/strata/terminal/python/bin/python3`). This
  candy installs no distro `python`, so a bare `python3` in a probe would depend on a package
  nothing here declares.
- **`download:` cannot carry a digest** (charly's `#Op` has no checksum field), so the two
  archives are fetched by a `run:` step that verifies the pinned sha256 and unpacks in the SAME
  layer. That is not a style choice: a `download:` into a staging path plus a later delete would
  leave 674 MB of archives in a lower layer forever. Filed as `opencharly/spec#397`.

## Related

- `/charly-strata:strata` — the BOX (this layer composed on the POD GPU contract base).
- `/charly-strata:strata-cli` — talks to a RUNNING server from the host (a different job).
- `/charly-ollama:ollama-layer` — the other local inference server in the org: GPU-agnostic and
  many small models, while this one is CUDA-only and serves one large one.
