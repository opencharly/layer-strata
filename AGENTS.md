# AGENTS.md — layer-strata

Strata — the Qwen3.8-Flash-Next inference engine as a charly family: the layer (`candy/strata`),
the image (`box/strata`) and the bed.

The authoritative rulebook is the umbrella `AGENTS.md` in `opencharly/opencharly` — Part I (R0–R10)
and Part II (the umbrella rules). Do not restate it here; this file adds only what is specific to
this repo. `README.md` is the user overview and never carries agent guidance.

## Load these skills first (R0)

- `/charly-image:layer` — candy authoring (`charly.yml`, plan-step verbs, `var:`, services).
- `/charly-image:image` — the `candy:` image entries this repo's box uses.
- `/charly-check:check` — the check verbs, the beds, and the change-class gate.
- `/charly-pod:pod` — `kind: pod` / deploy schema.
- `/charly-distros:cachyos` — the base distro behind `pod-cdi`.
- `/charly-internals:git-workflow` — before any git/PR action.

## This repo's own skills

- `.agents/skills/strata/SKILL.md` — the headless Strata gateway box: the image that SERVES
  Qwen3.8-Flash-Next on port 8080. **Read it before changing `box/strata` or probing a deployed
  gateway.**
- `.agents/skills/strata-layer/SKILL.md` — the engine layer itself: the pinned release artifacts,
  upstream's container entrypoint, the POD (CDI) contract, the probe helper. **Read it before
  changing `candy/strata`.**

## What is unique here

- **Nothing is compiled.** The candy installs upstream's PUBLISHED release artifacts — the Terminal
  (a bundled CPython + the `strata` CLI) and a signed, self-contained CUDA-13 engine COMPONENT —
  from the pinned `STRATA_VERSION`, into `/opt/strata/terminal` and
  `/opt/strata/components/engine/<component>/`. That is the layout upstream's own
  `tools/docker/Dockerfile` builds, and it is why the image needs no CUDA toolkit and no `nvcc`.
  **Never compile the engine here**: the compile path (`charly-build-engine.py`, upstream's
  `setup.py`) no longer exists upstream at v0.2.16.
- **Two digests, two boundaries.** Both archives are `sha256`-pinned in `var:` and gated by
  `sha256sum -c` before anything is unpacked. The engine COMPONENT is additionally checked by
  **upstream's own verifier** (`strata components engine --output json`): at BUILD with
  `STRATA_ENGINE_BACKEND=cuda` forced, so the question is about the artifact; at RUNTIME without it,
  so the question is about the card CDI injected. **Never re-implement that verifier** — signature,
  per-file sizes and the entrypoint's sha256 are upstream's.
- **The runtime is upstream's entrypoint.** `supervisord` runs `/opt/strata/entrypoint.sh run`,
  which turns the deployment's env into `strata launch --no-tui --access lan …`, migrates an
  older-layout volume, and drains on SIGTERM (`stop_timeout: 120`, upstream's own number). Do not
  reintroduce a charly-owned entrypoint, config merger or vision pass: those were DELETED because the
  runtime contract is upstream's product now (ledger `P3`).
- **The GPU contract is the POD's, not the VM's.** The image bases on `pod-cdi.pod-cdi` and requires
  `layer-cdi`; the driver user-space arrives from the host through CDI. **Never add `layer-nvidia`**
  — a baked driver user-space shadows the injected one (opencharly/layer-cuda#21). `layer-cuda` is
  not named either: `layer-cdi` requires it, and naming it here would pin one candy twice.
- **A model never enters the image.** The weights are 37–188 GB and licensed separately (Qwen
  Community License 1.0 / Apache-2.0 / Swift Open License). `/data` is a *named* volume here and a
  host **bind** on the deployment (`host: ~/.local/share/strata`: rootless + XDG).
- **Pictures are ON by default** (`VISION: cpu`), and upstream's launcher applies the choice on
  every start. The encoder BINARY ships inside the engine component; the encoder FILE (~0.9 GB of
  model data) is fetched once into the store and reused.
- **The configuration is the deployment's `env:`**, under upstream's OWN names — `MODEL`, `FAMILY`,
  `MODEL_PATH`, `CONTEXT`, `PARALLEL`, `VISION`, `KV`, `DRAFTING`, `DRAFT_VOCAB`, `GPU`/`GPUS`,
  `GPU_ROLES`, `TUNE`, `PRESET`, `STRATA_SET`, `PORT`, plus `API_KEY` as a REQUIRED secret (`secret_require`, so `charly config` mints it — an accepted name with no stored value injects nothing at all). The names the
  v0.2.16 entrypoint WARNS about and ignores (`HOST`, `LOW_RAM`, `REINSTALL`,
  `RESIDENT_BUDGET_GIB`, `KV_STREAMING`, `LAYER_SPLIT`, `CONFIG`) must never come back, and
  `GGUF_DIR` is not emitted (it is upstream's alias of `MODEL_PATH`).
- **Rootless discipline**: no privileged container, no root-owned host path, no `sudo`. The layer
  grants `a+rX` on `/opt/strata` rather than a `chown`, because nothing in that tree is written at
  run time and a `chown` would hardcode a uid that `user_policy` can move.
- **`LEDGER.md` is this repo's decision record** (`P1`–`P9`, plus the retired `V*` entries and why
  each cannot stand). Read it before changing the artifact source, the entrypoint, the GPU contract,
  the vision default or the context default.
- **Every probe lives in this candy**, so the beds declare almost no plan of their own (R3): six
  build-context probes and five runtime probes, and the runtime ones ask the server through ONE
  helper (`/opt/strata/charly-probes.py`, `health`/`models`/`chat`/`vision`) that also never starts or
  configures anything.

## Build / validate / test

- `charly box validate` at the repo root — the structural check and the change class's pre-flight.
- `charly box generate strata` — inspect the emitted Containerfile AND its
  `ai.opencharly.description` label. The plan steps are the artifact the validator reads, so **read
  them** rather than trusting the source. A multi-line `command:` is emitted into that label
  verbatim: a folded `>-` scalar inside a `python -c` program is a syntax error you will only see at
  gate time.
- The gate for a change here is `charly check run check-strata-gpu-pod` — the family's only bed. It
  runs the real engine, so it needs the **GPU venue** (a host that can build an image and has a card
  the CDI spec reaches) and a **provisioned model store**, and is therefore run on demand rather
  than in the default roster.
- The first start may MOVE an operator's store (`/data/models|packs|mtp` →
  `/data/Strata-data/…`, rename-only, idempotent) and may re-fetch the encoder. Record what actually
  happened in the PR body; never "fix" it by hand.

## Landing

PR-only. The org-required `charly/pr-validator` is the gate and arms native auto-merge on a PASS;
`main` is squash-only and direct pushes are disabled. History lives in `CHANGELOG/`, written by
`tag-on-merge` from the PR body at merge time — the PR body *is* the changelog.
