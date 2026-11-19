# LEDGER — the v0.2.16 cutover: released artifacts, upstream's entrypoint, the POD contract

This is the decision record for **one change**: `layer-strata` moves from *compiling* Strata
`v0.1.44.1` inside the image to *installing* the artifacts upstream `v0.2.16` publishes, running
them through upstream's own container entrypoint, and composing the POD (CDI) GPU contract
instead of the VM one.

It SUPERSEDES `V1`–`V9` below, which recorded the pictures-on vision pass. That pass, the overlay
merge, the extra-argv merge and the engine bake are all gone with the source tree they patched, so
the entries that described them are retired here rather than left standing (R5, claim-keyed).

Read an entry as: **decision → why → evidence → the control that keeps it true → what would
invalidate it.** Anything measured was measured on this host (RTX 4080 SUPER, driver 615.78.08) on
2026-11-19; anything read is cited by path at the pinned upstream tag **v0.2.16**, or `path:line`
inside the released Terminal.

---

## The problem this ledger answers

Upstream moved, and it was not a version bump. At `v0.1.44.1` the tree the candy baked against
was `Dockerfile`, `setup.py`, `CMakeLists.txt`, `src/`, `include/`, `serve/`, `requirements.txt`.
At `v0.2.16` **every one of those is gone**, replaced by `engine/` (its own CMake), `terminal/`
(bundled CPython + `strata_cli`/`strata_control`/`serve`), `app/`, `tools/` and `setup.sh`.

`candy/strata/charly-build-engine.py` imported upstream `setup.py`'s own functions, so it could
not survive; and the four charly-authored runtime scripts (`charly-entrypoint.sh`,
`charly-vision.py`, `charly-merge-config.py`, `charly-merge-args.py`) were superseded by
upstream's `tools/docker/` container contract — a SECOND implementation of a product surface
that had already cost this family two silent failures (the inert `VISION` knob, the cache
non-hermeticity that made two builds of one commit disagree).

---

## P1 — Bake the RELEASED artifacts; do not compile

**Decision.** The candy installs upstream's published `strata-control-0.1.62-linux-x86_64.tar.gz`
(the Terminal) and `strata-engine-0.1.62-linux-x86_64-cuda-cuda13.tar.gz` (the engine COMPONENT)
from the pinned `v0.2.16` release, `sha256`-pinned, into `/opt/strata/terminal` and
`/opt/strata/components/engine/<component>/` — exactly the layout upstream's own
`tools/docker/Dockerfile` builds.

**Why.** "The engine is in the image, so the first start never compiles it" was always the
layer's job (the bake decision in the family's old `plan/strata-layer-and-pod.md`, its `D6`). Upstream now publishes the compile's OUTPUT, and its own container
image installs those two archives; baking them serves the same decision without a 18–25 minute
compile, without `nvcc`, and without the stamp-that-can-lie failure mode (upstream #2054) that the
old bake needed two probes to police.

**Evidence.** The release assets' own digests, measured on this host with `sha256sum`:

```
045b6a7d7fbfbddab814794db5763d6244c887a394403b9fe0e8a4714d9bef8c  strata-control-0.1.62-linux-x86_64.tar.gz
6723e1b6b6042bfe1d368723ebf873afb0fa65f4f1908d948dd865098f6cfb9e  strata-engine-0.1.62-linux-x86_64-cuda-cuda13.tar.gz
```

and the component's own report from the released Terminal, on this host:

```
$ STRATA_COMPONENTS_DIR=<components> terminal/bin/strata components engine --output json
{"backend": "cuda", "backend_source": "nvidia-smi", "installed": [{"version": "0.1.62", …, "signed": true}],
 "usable": true, "problems": []}
$ terminal/bin/strata --version
strata 0.2.16 (build 0.1.62; python 3.12.15 at …/terminal/python/bin/python3.12)
```

**Control.** Both archives are digest-gated (`sha256sum -c`) before anything is unpacked, and the
component must then pass upstream's own verifier at build (`strata-engine-component`) and at
runtime (`strata-engine-usable`). A cache hit is verified exactly like a fresh fetch.

**Invalidated by.** Upstream withdrawing the published artifacts, or renaming the component id
(`<version>-<platform>-<backend>-<variant>`) — then `STRATA_ENGINE_COMPONENT` and the two `file:`
probes move with it.

## P2 — The component is verified by upstream's verifier, at two different boundaries

**Decision.** The signature is never re-implemented. At build the component is resolved with
`STRATA_ENGINE_BACKEND=cuda` (upstream's own override) so the question is about the ARTIFACT; at
runtime it is resolved with no override so the question is about the CARD.

**Why.** `strata components engine` checks the ed25519 signature of `engine-component.json`, every
file's recorded size, the entrypoint's sha256 and its executable bit, and reports the package this
machine would start (`strata_control/engine_component.py`, `resolve`/`verify`/`verify_signature`).
Re-implementing any of that is the duplication R2 forbids — and the split is what makes each check
mean one thing. Without the override the build context's answer depends on the BUILDER: a builder
with no card in `/sys/bus/pci` reports backend "cpu" and calls a good CUDA package unusable.

**Evidence.** Measured on this host with the builder's condition simulated (a `PATH` with no
`nvidia-smi`): the resolver still found the card through `sysfs pci vendor`; forcing the backend
returns `"backend_source": "environment"` and the same `usable: true`. So the override changes the
QUESTION, not the answer, and it is the only way to ask the artifact question where no card exists.

**Control.** `strata-engine-component` fails on `signed: false`, a version/variant mismatch, a
non-empty `problems`, or a non-executable engine; `strata-engine-usable` fails when the runtime
resolution is not `usable: true`/`backend: cuda`/`signed: true`.

**Invalidated by.** Upstream removing `STRATA_ENGINE_BACKEND`, or separating "signed" from
"usable" in the JSON.

## P3 — The runtime is upstream's entrypoint; charly's four scripts are deleted

**Decision.** `tools/docker/entrypoint.sh`, `healthcheck.sh` and `strata-wrapper.sh` are installed
from the pinned tag (and pinned by CONTENT as well: a tag can be moved, and these are the files
the running service executes). The supervisord service runs `/opt/strata/entrypoint.sh run` with
`stop_timeout: 120`. `charly-entrypoint.sh`, `charly-vision.py`, `charly-merge-config.py`,
`charly-merge-args.py` and `charly-build-engine.py` are DELETED.

**Why.** The runtime contract is upstream's product now: config presets, `STRATA_SET`, the
`--access lan` key rule, the `/data/Strata-data` layout and the older-volume migration are all in
the entrypoint. A second implementation inside charly is exactly the duplication R2 forbids, and
it is the part that kept breaking silently.

**Evidence.** The entrypoint's own contract, read at the tag: `strata launch --no-tui --access lan
--port $PORT --data-dir /data/Strata-data`, the legacy-env warning list, the `models`/`packs`/`mtp`
rename, the `MODEL_PATH` guard, `--api-key-env STRATA_LAUNCH_KEY`, and `--stop` on SIGTERM. The
two-minute stop is upstream's own instruction (`docker run --stop-timeout 120`, compose
`stop_grace_period: 2m`), because a stop drains, unloads and frees the page-locked RAM.

**Control.** `strata-container-scripts` asserts all three are installed, readable and executable;
the three digests are verified in the same step that grants them.

**Invalidated by.** Upstream moving the entrypoint out of `tools/docker/`, or changing how it
reads its settings.

## P4 — The image is a POD-contract image: `base: pod-cdi`, `require: layer-cdi`

**Decision.** `require:` is `layer-supervisord` + `layer-cdi` (newest merged tag). `layer-nvidia`
and `layer-build-toolchain` are dropped, and `layer-cuda` is NOT named — `layer-cdi` requires it
itself. `box/strata` becomes `base: pod-cdi.pod-cdi`, imported from `opencharly/pod-cdi` at a
merged tag.

**Why.** A pod does not own its GPU driver: the kernel module is host-global, so the driver
user-space must come from the HOST and be injected per container through the toolkit's CDI spec.
An image that bakes its own user-space does not merely duplicate it — it WINS the SONAME
resolution, so `libnvidia-ml.so.1` resolves to the baked copy, `nvidia-smi` exits 18 with
"Driver/library version mismatch", and anything sizing memory through NVML silently degrades
(measured: opencharly/layer-cuda#21). The old composition was exactly that: a VM-contract GPU
stack on an image deployed as a pod. `layer-cdi` is the repo that owns the other side, and its own
plan steps FAIL the build if a host-coupled library or `nvidia*` binary survives.

Naming `layer-cuda` here as well would pin one candy twice in one scope, which is a hard refusal —
and the pin that MATTERS is `layer-cdi`'s own (`layer-cuda:v2026.323.0252`, the release that
dropped `require: layer-nvidia`, so a pod cannot be dragged back onto the VM driver layer).

**Evidence.** `charly box inspect strata --format base` → `pod-cdi.pod-cdi`; the generated
Containerfile builds `pod-cdi.arch.arch-builder` → `pod-cdi.arch.arch` → `strata`, and the runtime
resolution `uid 1000 / user user / gid 1000` comes from the imported box. `layer-cdi`'s
`cdi-no-baked-driver-libs`/`cdi-no-baked-driver-binaries` run in this image's build.

**Control.** `layer-cdi`'s own build steps (inherited, not duplicated here), plus the runtime
`cdi-injected-driver-matches-module` probe that layer carries.

**Invalidated by.** A GPU substrate that injects the driver some other way, or `pod-cdi` changing
its own base or its layer-cdi pin.

## P5 — Pictures are on by default, and upstream applies the knob on every start

**Decision.** `VISION: cpu` stays the family default — pictures ON, read by the encoder on the
CPU. `gpu` opts into the card's reader, `off` turns them off. The charly vision pass is deleted;
upstream's launcher applies `--vision` on every start.

**Why.** `cpu` takes nothing from the card, and this engine's expert cache already runs VRAM-tight
(measured: 413 MiB free with everything loaded on the 16 GB bed venue). Upstream defaults `VISION`
to `off`; the family's posture is on, and the layer says so by DEFAULting the variable rather than
by patching a config. The old V1/V2/V3/V4 entries recorded a pass that existed only because
upstream wrote the `vision` section once, in `setup.py`, and never again; `v0.2.16` records the
choice in the PRESET and re-applies it per start, so the pass has no mechanism left to patch.

**Evidence.** The entrypoint's settings block maps `VISION` (`off|on|gpu|cpu`, with `no`/`yes`
accepted) straight to `--vision` on every start; `strata launch --help` documents `on` as "the
reader by your graphics memory: the CPU reader under 24 GB, the GPU reader from 24 GB", which is
why this layer states `cpu` rather than `on` — on the bed venue the two agree, on a 24 GB+ card
they do not.

**Control.** The bed asserts `/health` reports `"images": true` with NO vision variable in its
env — the default is what is under test — and then round-trips a real PNG whose answer must name
the colour. A config flag cannot fake either.

**Invalidated by.** Upstream re-defaulting `VISION`, or separating "can read pictures" from "is
reading pictures" in `/health`.

## P6 — The env surface is upstream's own names; the retired ones are DELETED

**Decision.** `MODEL`, `FAMILY`, `MODEL_PATH`, `CONTEXT`, `PARALLEL`, `VISION`, `KV`, `DRAFTING`,
`DRAFT_VOCAB`, `GPU`/`GPUS`, `GPU_ROLES`, `TUNE`, `PRESET`, `STRATA_SET`, `PORT`, and `API_KEY` as
the secret. `STRATA_RUN_ARGS`, `STRATA_OVERLAY_JSON`, `LOW_RAM`, `STRATA_MEMORY_LIMIT_MIB`,
`REINSTALL`, `KV_STREAMING`, `RESIDENT_BUDGET_GIB`, `LAYER_SPLIT`, `HOST`, `GGUF_DIR`,
`VISION_MMPROJ_URL`, `VISION_MMPROJ`, `VISION_THREADS`, `VISION_TOKENS`, `STRATA_DATA` and
`STRATA_ENGINE` are gone from the candy.

**Why.** The entrypoint WARNS and ignores `HOST`, `LOW_RAM`, `REINSTALL`, `RESIDENT_BUDGET_GIB`,
`KV_STREAMING`, `LAYER_SPLIT` and `CONFIG`, so emitting them would be a setting that looks set and
does nothing — the class of falsehood the old ledger's O-entries existed to prevent. `GGUF_DIR`
still works upstream as an alias of `MODEL_PATH` and is not emitted: one surface per thing. The
`STRATA_*` knobs charly invented (`STRATA_RUN_ARGS`, `STRATA_OVERLAY_JSON`, `VISION_MMPROJ*`,
memory limits, the mock engine) have no counterpart because charly no longer writes or reads the
run config — server-behaviour keys are the engine's own (`strata profile`, `GET /config`,
`STRATA_SET`).

**Evidence.** The v0.2.16 `tools/docker/Dockerfile` `ENV` block and the entrypoint's settings and
legacy-warning sections; `docs/DOCKER.md`'s settings table.

**Control.** The candy's env IS the surface, and every name in it is one the entrypoint reads.
The claim-keyed grep at the bottom of this file is the sweep that proves the retired names appear
nowhere in this repo.

**Invalidated by.** Upstream adding a name (then the candy may adopt it) or re-reading a retired
one.

## P7 — The secret is `API_KEY`, and it is REQUIRED, not accepted

**Decision.** `secret_require: [{name: API_KEY}]` — upstream's own name, and the required form.

**Why.** `STRATA_API_KEY` was charly's name, projected into `API_KEY` by the deleted entrypoint.
The entrypoint hardcodes `--access lan`, Strata refuses to serve beyond loopback without a key, and
when it is handed nothing it MINTS one into the volume — so "a key is always on" is upstream's
product invariant, not a deployment's choice. A `secret_accept` would therefore document a keyless
posture that cannot exist. Worse, it would be INERT: measured on this host, an accepted name with no
value in the credential store injects **nothing** — no podman secret, no environment variable, and
no warning — because only a required name is on the mint path
(`plugin-deploy-pod`'s `EnsureBoxChainSecrets` → `deploykit.EnsureCandySecret(dep, required, …)`).
That is a setting that looks set and does nothing, which is the class of falsehood this ledger
exists to keep out.

**Evidence.** Measured 2026-11-19 on the bed:

```
# with secret_accept and no stored value
$ grep -E "^Secret=" ~/.config/containers/systemd/charly-check-strata-gpu-pod.container
                                        (nothing)
$ charly secrets list | grep API_KEY
                                        (nothing)
# with secret_require
$ charly config check-strata-gpu-pod && grep -E "^Secret=" ~/.config/containers/systemd/charly-check-strata-gpu-pod.container
Secret=charly-check-strata-gpu-pod-api-key,type=env,target=API_KEY
$ charly secrets list | grep API_KEY
charly/secret/API_KEY
```

so `charly config` mints a 32-byte token for a required name and the unit delivers it as
`Secret=…,type=env,target=API_KEY`. The engine still reads its key from `API_KEY`
(`--api-key-env STRATA_LAUNCH_KEY`), and the entrypoint records the effective one in
`/data/state/api-key` (`strata launch --show-key`), which is where the probes read it.

**Control.** `strata-api-gate` is posture-BRANCHED rather than fixed: with a key in force
`/v1/models` must answer 401 without it and 200 with it; with none it must answer 200 (the branch a
hand-made deployment with no charly secret takes). The bed's key comes from the candy's required
secret, so the keyed branch is what the bed exercises.

**A consumer consequence, stated where the decision is.** Because the name is REQUIRED, a deployment
of this image is not instantiable until `charly config` has run once: that is what mints
`charly/secret/API_KEY` and writes `Secret=…,type=env,target=API_KEY` into the unit. A deployment
configured some other way must supply `API_KEY` itself. The PR body's breaking-change line carries
the same sentence, because it is the one thing a consumer has to DO.

**Invalidated by.** Upstream serving unauthenticated beyond loopback, renaming the variable, or
charly changing which declarations get minted.

**Control.** `strata-api-gate` is posture-BRANCHED rather than fixed: with a key in force
`/v1/models` must answer 401 without it and 200 with it, and with no key it must answer 200 —
a fixed either-way assertion would be red on one of the two legal deployments, or blind to the
other.

**Invalidated by.** Upstream serving unauthenticated beyond loopback, or renaming the variable.

## P8 — The two standing postures, now enforced by other means

**Rootless.** No privileged container, no root-owned host path, no `sudo`; the GPU arrives as a CDI
device and the store is a host bind under the operator's XDG data directory. The workload's uid is
1000 in the image, and container **0** on a POD deploy — under `userns=host` the container's root is
the invoking host user, and that is the only mapping under which a host-owned bind stays writable
while the CDI file mounts resolve (`plugin-deploy-pod#81`: an idmapped mount needs `CAP_SYS_ADMIN`
in the userns owning the filesystem's superblock, which no rootless container can hold).
The image grants `a+rX` on `/opt/strata` instead of a `chown`, because nothing in that tree is
written at run time and a `chown` would hardcode a uid that `user_policy` can move.

**A model never enters the image.** The weights are 37–188 GB, licensed separately from the engine
(Qwen Community License 1.0 / Apache-2.0 / Swift Open License). What IS in the image is software:
the Terminal, the signed engine component, and the `strata-vision` encoder BINARY. The encoder
FILE (~0.9 GB of model data) is fetched once into the store and reused.

**Control.** No `download:` step targets a weight or an encoder file, and the probes assert the
engine and the encoder binary rather than any model artifact. `box validate` carries no model.

**Invalidated by.** A licensing decision to ship weights, or an encoder small enough to bake.

## P9 — `CONTEXT` stays 64K, but it is now a setup-time value with a different move path

**Decision.** `CONTEXT: "65536"` remains the default. It is a SETUP-TIME choice, and an existing
deployment moves by re-saving its preset (or by dropping the run settings in `/data/install`).

**Why.** The old move path was `STRATA_RUN_ARGS=--max-context …`, a charly surface that no longer
exists. The launcher records `--max-context` from `--context` into the run settings, and a model
already set up keeps its recorded value — so the default applies to a NEW deployment, and an
existing one either re-saves (any start with settings does that) or lets the entrypoint drop run
settings that name another card, which it does by itself and says so.

**Evidence.** `strata_cli/launch/runner.py` writes `--max-context` straight from the chosen
context; `strata launch --help` documents the choice; the entrypoint deletes
`/data/install/strata-*.json` when they name a missing component or another card.

**Control.** The bed pins `CONTEXT: "65536"` and asserts `/health` reports it — a value that
differs from the engine's own 32768 recommendation for that card, so the assertion can fail.

**Invalidated by.** The launcher clamping a requested context, or moving the run settings.

---

## Retired entries (R5, claim-keyed)

| Retired | Why it cannot stand |
|---|---|
| `V1` pictures on by default (the decision's WHY) | stands as a posture, now `P5`; its evidence about a `--vision` mapping in `setup.py` is gone |
| `V2` a charly-owned vision pass runs LAST | the pass is deleted; upstream re-applies the choice per start |
| `V3` the pass writes the setup-owned key | no charly writer exists; `SETUP_OWNED` is gone |
| `V4` the `lazy_load` pair is settled by the pass | upstream owns the pair; the launcher's own settings decide it |
| `V5` encoder software in the image, data never | stands as `P8`; the binary now ships inside the component, not from a bake |
| `V6` the family→encoder table is charly DATA | the table is upstream's again, since charly no longer picks an encoder |
| `V7` a model outside the table names its encoder | the surface (`VISION_MMPROJ_URL`) is retired with the pass |
| `V8` the deployment's model choice stays local | stands, unchanged (`P8`, and this repo still ships mechanism only) |
| `V9` 64K default + `--vram-reserve-mib 1024` | the context default stands as `P9`; the reserve default is retired with `STRATA_RUN_ARGS` |
| `D6` "the engine is baked exactly as upstream's Dockerfile COMPILES it" | upstream's Dockerfile no longer compiles; it installs (`P1`) |
| `charly-build-engine.py`, the `source_hash(ENGINE_SOURCES)` stamp, `/opt/strata/engine/BUILD.json` | deleted; the component's signed manifest is the stamp now |
| `charly-entrypoint.sh`, `charly-merge-config.py`, `charly-merge-args.py`, `charly-vision.py`, `SETUP_OWNED` | deleted (`P3`) |
| `STRATA_RUN_ARGS`, `STRATA_OVERLAY_JSON`, `LOW_RAM`, `STRATA_MEMORY_LIMIT_MIB`, `REINSTALL`, `KV_STREAMING`, `RESIDENT_BUDGET_GIB`, `LAYER_SPLIT`, `HOST`, `GGUF_DIR`, `STRATA_DATA`, `STRATA_ENGINE`, `STRATA_API_KEY` | retired by upstream or by this cutover (`P6`, `P7`) |
| `/data/config/strata-<model>.json` as THE run config | the run settings live in `/data/install/`, the presets in `/data/state/` (`P3`) |
| `O1` — the cited `D1–D16` ledger absent from `origin/main` | still open as opencharly/opencharly#556; the D-numbers it names are gone from this repo with the compile path |
| `box/strata`, the root bed `check-strata-gpu-pod`, the box skill and the image `defaults:` | MOVED, not retired: they live in `opencharly/pod-strata` (opencharly/opencharly#1174). `P4` above records the decision as taken HERE, which is history and stays true; this repo keeps the candy, the layer skill and this ledger. |

---

## Open risks (the first start does these; they are not defects to hide)

| Risk | What happens | Mitigation |
|---|---|---|
| The entrypoint MOVES an older-layout volume | `/data/models`, `/data/packs`, `/data/mtp` → `/data/Strata-data/…`, rename-only, idempotent, skips its own mounts | upstream's own migration; the bed binds the operator's store, so the move is recorded in the bed's evidence. A rollback to a v0.1.x image needs the reverse move |
| A pictures-on first start re-fetches the encoder (~0.9 GB) | `/data/vision` is not in the move list, and the encoder is model data fetched per layout | network available on the venue; the fetch is upstream's |
| The prepared pack may not be reusable by the 0.2.16 engine | the first start may rebuild it (tens of minutes) | let it run; the bed's `eventually` window is 90 minutes and its evidence says which happened |
| The bed needs the GPU venue | it is excluded from the default roster | run on demand on a host with the card AND the staged shards |

---

## How this change is gated

1. **Build context, no card needed** — `charly box validate`, `charly box generate strata` (the
   emitted Containerfile and its `ai.opencharly.description` label are the artifact, and are READ),
   `charly box build strata`, then the candy's six build probes, which include upstream's own
   component verifier.
2. **The live bed** — `charly check run check-strata-gpu-pod` on this venue: the real engine, the
   provisioned store, the CDI-injected card, the key gate, a real picture and a completion.

Every probe this change adds names an artifact that does not exist on the pre-change tree
(`/opt/strata/terminal/`, `/opt/strata/components/engine/`, `entrypoint.sh`, `strata --version`
reporting `0.2.16`), so the coverage cannot pass without the change.
