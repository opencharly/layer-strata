# AGENTS.md — layer-strata

Strata — the Qwen3.8-Flash-Next inference engine as a charly family: the layer
(`candy/strata`), the image (`box/strata`) and the beds.

The authoritative rulebook is the umbrella `AGENTS.md` in `opencharly/opencharly` — Part I (R0–R10)
and Part II (the umbrella rules). Do not restate it here; this file adds only what is specific to
this repo. `README.md` is the user overview and never carries agent guidance.

## Load these skills first (R0)

- `/charly-image:layer` — candy authoring (`charly.yml`, plan-step verbs, `var:`, services).
- `/charly-image:image` — the `candy:` image entries this repo's box uses.
- `/charly-check:check` — the check verbs, the beds, and the change-class gate.
- `/charly-pod:pod` — `kind: pod` / deploy schema.
- `/charly-distros:cachyos` + `/charly-distros:nvidia` + `/charly-distros:cuda` — the base and the
  GPU stack this family composes.
- `/charly-internals:git-workflow` — before any git/PR action.

## What is unique here

- **The engine is baked at image build** (`candy/strata/charly-build-engine.py`), exactly as
  upstream's own Dockerfile does it, so `engine/BUILD.json` carries `source: local` with the
  matching `src` hash and the first start never compiles it. **Never modify the Strata source
  tree**: any edit changes `source_hash(ENGINE_SOURCES)` and silently re-triggers a compile.
- **The stamp is written LAST** by that script, and a runtime check cross-checks it against
  `engine/strata --version` — upstream #2054 shows a failed build can leave a stamp that lies.
- **A model never enters the image.** The weights are 37–188 GB and licensed separately (Qwen
  Community License 1.0 / Apache-2.0 / Swift Open License). `/data` is a *named* volume here and a
  host **bind** on the deployment (`host: ~/.local/share/strata`: rootless + XDG, ledger D15/D16).
- **The configuration is the deployment's `env:`** — the engine's own documented variables, renamed
  by nothing — plus `charly-overlay.json`, merged into the volume's run config by
  `charly-merge-config.py`, which **refuses setup-owned keys** (ledger D11). Read the ledger before
  touching `SETUP_OWNED`.
- **Rootless discipline**: no privileged container, no root-owned host path, no `sudo`.
- Every probe lives in **this candy**, so the beds declare no plan of their own (R3). Adding a bed
  should mean adding no assertions.

## Build / validate / test

- `charly box validate` at the repo root — the structural check and the change class's pre-flight.
- `charly box generate strata` — inspect the emitted Containerfile. The plan steps and their OCI
  labels are the artifact the validator reads, so **read them** rather than trusting the source.
- The gate for a change here is `charly check run check-strata-gpu-pod` — the GPU bed (the GPU-free mock mode is a runtime posture, not a bed)
  (the engine's scripted `--engine mock` mode: no card, no model). It needs the **image**, so it
  needs a host that can build one; `check-strata-gpu-pod` is the real-engine bed, needs the GPU venue
  and a provisioned model store, and is run on demand rather than in the default roster.

## Landing

PR-only. The org-required `charly/pr-validator` is the gate and arms native auto-merge on a PASS;
`main` is squash-only and direct pushes are disabled. History lives in `CHANGELOG/`, written by
`tag-on-merge` from the PR body at merge time — the PR body *is* the changelog.
