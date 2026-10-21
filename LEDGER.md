# LEDGER — pictures on by default for every Strata pod

This is the decision record for one change: **the `strata` layer serves pictures by default, and the
`VISION` knob finally takes effect on a model that is already installed.**

It exists because this family's comments cite a ledger — `opencharly/opencharly`,
`plan/strata-layer-and-pod.md`, entries D1–D16 — that is **absent from that repo's `origin/main`**
(open item **O1** below). A citation nobody can resolve is a stale claim, so the decisions for this
change are written HERE, in the repo that carries them, with the command or line that proves each one.

Read an entry as: **decision → why → evidence → the control that keeps it true → what would
invalidate it.** Anything measured was measured on this host on 2026-10-21; anything read is cited as
`path:line` at the pinned engine tag **v0.1.44.1**.

---

## The problem this ledger answers

`VISION` was dead configuration on every installed model.

- The candy exposes `VISION` (`candy/strata/charly.yml`), and the entrypoint passes it to upstream's
  installer: `--vision "$VISION"` (`candy/strata/charly-entrypoint.sh`).
- That install pass runs **only** when the run config is absent or `REINSTALL=1`.
- So on any deployment that already has `/data/config/strata-<model>.json` — every restart, every
  redeploy, every community pack launched through `STRATA_RUN_ARGS` — `VISION` reached no code that
  writes anything. `/health` kept answering `"images": false`, with no error: the knob looked set and
  did nothing.
- The Layer-B overlay could not carry it either: `"vision"` is `SETUP_OWNED`, and
  `charly-merge-config.py` refuses setup-owned keys by design (D11).
- Behind both: upstream's settings validator refuses to set `lazy_load: true` on a config that reads
  images (`serve/runconfig.py:92-93`, whose only call site is the settings-write path at `:126`), and
  upstream documents the key as "text only" (`:33`). The LOAD path (`load()`, `:175`) does not
  validate the pair — measured: the engine starts with both and reports `images: true`. So a
  charly-written section beside the baked overlay's `lazy_load: true` is not a crash, it is a config
  upstream's own API declines to write.

---

## V1 — Pictures are ON by default, read on the CPU

**Decision.** The candy's default becomes `VISION: cpu`. `gpu` opts into the card's reader;
`no`/`off` turns pictures off. `yes`/`on` are accepted as aliases for `cpu`, and say so in one line.

**Why.** `cpu` takes nothing from the card, and this engine runs its expert cache VRAM-tight:
measured on the 16 GB bed venue, the live engine reported **413 MiB of VRAM free** with everything
loaded. Upstream measured the card's reader **slower for text on a 16 GB card** (46.0 vs 48.4 tok/s,
`docs/DETAILS.md`), so "on by default" and "on the card by default" are not the same bargain here.

**Evidence.** `serve/runconfig.py` gates the pair; `setup.py:6306` maps `--vision yes` to `gpu`
(`{"yes": "gpu", "no": "none"}.get(a.vision, a.vision)`) — so the alias is DELIBERATELY not upstream's
mapping, and the pass prints why: silently inheriting `yes → gpu` would put a 1.2–1.4 GB reader on a
card that has 413 MiB to spare.

**Control.** `strata-vision-pass` (build context) asserts the emitted section for the default: the CPU
reader, `gpu: false`, the device's token default, the CPU thread count. `check-strata-gpu-pod`
asserts `/health` reports `"images": true` with NO `VISION` in the bed's env, i.e. the default is what
is under test.

**Invalidated by.** Upstream changing what `--vision cpu` means, or the engine gaining a CPU-free
alternative. Re-read `setup.py`'s `VISION` dict at the pin before changing the reader's defaults.

## V2 — A charly-owned vision pass is the writer, and it runs LAST

**Decision.** `candy/strata/charly-vision.py` writes the run config's `vision` section on every
start, after the install pass, the overlay merge and the extra-argv merge, immediately before the
launch.

**Why.** `setup.py` is the only other writer and it does not run on an installed config (above). The
pass must be last because it enforces an invariant (`V4`) that the overlay can contradict, and the
engine reads the config once, at launch.

**Evidence.** The entrypoint's own order — install → overlay → `STRATA_RUN_ARGS` → **vision** →
launch (`candy/strata/charly-entrypoint.sh`). The section's shape is copied from
`setup.py:6791-6796` (`exe`, `mmproj`, `model`, `gpu`, `max_tokens`, and `threads` for the CPU reader
only), so the engine cannot tell the two writers apart.

**Control.** The pass is idempotent and says `already in effect; nothing to write` when nothing
changed — asserted by the second run inside `strata-vision-pass`.

**Invalidated by.** Moving the section into a schema the overlay may carry (which would delete this
pass), or upstream making `setup.py` re-entrant on an installed config.

## V3 — It writes the setup-owned key rather than teaching the overlay to

**Decision.** The pass writes `vision` into the volume config directly: atomic temp-file +
`os.replace`, the engine's `indent=1`, and a `<name>.bak`, exactly like the two merge helpers. The
overlay helper's `SETUP_OWNED` rule is left untouched.

**Why.** `charly-merge-config.py` refuses setup-owned keys because setup rewrites them on a settings
pass — a rule that is still correct. The difference is OWNERSHIP: `setup.py` owns that key only when
it runs, and here it never runs. So the pass takes ownership of the one key on the one path it owns,
instead of weakening a guard that protects sixteen other keys.

**Evidence.** `SETUP_OWNED` in `candy/strata/charly-merge-config.py` still contains `"vision"`. The
README's "escape hatch" (a hand-written config on the volume is honoured because the install pass
seeds only when none exists) is now the MECHANISM rather than folklore.

**Control.** `strata-vision-pass` proves a hand-written config gains the section and keeps every
other key; the `check-strata-gpu-pod` step asserts the volume's own file carries it.

**Invalidated by.** Upstream removing `vision` from its setup-owned set (then the overlay could carry
it), or `POST /config` learning the key (today it refuses load-time keys).

## V4 — The `lazy_load` pair is settled by the pass, not by the overlay

**Decision.** When the pass writes a `vision` section and the config has `lazy_load: true`, the pass
sets `lazy_load: false` and prints one line saying why. When pictures are off, `lazy_load` is left
exactly as the deployment set it.

**Why.** Upstream's settings validator refuses the pair, so this is not a preference — leaving it
would manufacture a configuration upstream's own API declines to write. The overlay keeps
`lazy_load: true` because a fast first text answer matters to the common, picture-less deployment.

**Evidence — and the correction that came out of writing this ledger.** An earlier version of this
entry claimed the pair made the container a crash-loop. That was WRONG, and it was caught before the
push, not after: the refusal lives in the settings validator only —

```
$ grep -n "check(" serve/runconfig.py
81:def check(key: str, v, cfg: dict):
126:    checked = {k: check(k, v, cfg) for k, v in changes.items()}     # the ONLY call site: settings write
$ sed -n '/^def load/,/^def /p' serve/runconfig.py
def load(path): cfg = json.loads(...); ...                          # no pair validation
```

and measured live: a config carrying BOTH starts and reports `"images": true`. The validator's own
message is quoted at `serve/runconfig.py:92-93`:
`if key == "lazy_load" and v and cfg.get("vision"): raise ValueError("lazy_load: lazy loading is
text-only, and this model reads images (\"vision\")")`. So the pass aligns the config with upstream's
contract; it does not prevent a crash. The one line it prints says exactly that.

**Control.** Both checks assert `lazy_load` is not true after the pass (`strata-vision-pass` on a
synthetic config, the bed on the live volume).

**Invalidated by.** Upstream allowing lazy loading with images (then the pass should stop forcing it
and the one line should go), or upstream enforcing the pair on the LOAD path (then the wording shifts
back to crash-prevention — and the measurement above is what would need re-running).

## V5 — The encoder's SOFTWARE is in the image; its DATA never is

**What this change does and does not do.** The bake PRE-EXISTS on `main`: `charly-build-engine.py`
already builds `strata-vision` (`STRATA_BUILD_VISION: "1"`, and `BUILD.json` records
`vision: "gpu"` with a `vision_src` hash). `charly-build-engine.py` is **not among this change's
files**. What this change adds is the DECISION that the encoder belongs in the image while its data
never does, and the two checks that assert it — because before this change nothing said either way
and nothing verified it.

**Decision.** The `strata-vision` binary (222,994,464 bytes) stays in the image, baked beside the
engine by that pre-existing bake. The `mmproj` encoder file (907,543,008 bytes) is fetched once into
the model store (`/data/vision/`) and reused. No `download:` plan step ever puts an encoder in the
image.

**Why.** The binary is software: it must be there before the first start, or every deployment
compiles or fails. The encoder file is model data — licensed with the weights, as large as a small
model, and useless without the model it belongs to. Baking it would break the family's own invariant
that a model never enters the image, and would ship Qwen-licensed weights inside a published layer.

**Evidence.** `engine/BUILD.json` = `{"source": "local", "version": "0.1.44.1", "vision": "gpu"}` on a
built image, with the binary beside the engine — confirmed in the image this change was gated on by
`charly check box strata`: `PASS check the image-encoder binary is baked beside the engine
[strata-vision-binary]` and `PASS ... [strata-vision-stamp]`. The downloaded encoder:
`sha256 b1a82259702816a5330d7bd7607cd9676b11780e79ff7348c21103ff3ce49bd0`, 907,543,008 bytes,
GGUF magic `GGUF` — a size and hash upstream itself pins for the nvfp4 family (`mmproj_sha256`).

**Control.** `strata-vision-binary` (file exists) and `strata-vision-stamp` (`BUILD.json` records
`vision` ∈ {cpu,gpu} **and** a `vision_src` hash — the same "a stamp can lie" discipline as the
engine's own stamp check, upstream #2054). The presence of the binary in the image is thus asserted,
and the ABSENCE of the encoder file from the image is a property of the plan, not a check.

**Invalidated by.** An encoder small enough to bake, or a licensing decision to ship it — neither is
true today.

## V6 — The family→encoder table is DATA, and a check keeps it honest

**Decision.** `charly-vision.py` carries the family→encoder table (qwen, swift, coder, unsloth,
nvfp4 — revision-pinned URLs as upstream's `hf()` builds them; `qwen36` = no encoder, because
upstream declares `"vision": False` for it). The build-context check `strata-vision-table` asserts
every row equals `setup.FAMILIES` / `setup.OWN_PATH_FAMILIES` **inside the built image**.

**Why.** The pass may not import upstream's `setup.py` at runtime: the wrapper deliberately depends on
upstream's documented argv, never its internals, and the import is not free. Copying data is
acceptable only when a control prevents it from drifting — otherwise advancing the pin silently points
deployments at the wrong encoder.

**Evidence.** At the pin: `setup.FAMILIES` = {qwen, swift, coder, unsloth, nvfp4} with
`mmproj_hf` + `mmproj` per family, e.g. qwen =
`ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF @ ed59f92082b1e93c0e96d60a8b11aab089b52f09` +
`mmproj-Qwen3.8-Flash-Next-BF16.gguf`; `setup.OWN_PATH_FAMILIES["qwen36"]["vision"] is False`.

**Control.** `strata-vision-table`. It fails on a repin whose tables moved, naming the family.

**Invalidated by.** Upstream restructuring those tables (the check must then be updated in the same
PR — that is the point of it).

## V7 — A model outside the table must NAME its encoder

**Decision.** A family absent from the table, and no `VISION_MMPROJ_URL`, leaves pictures OFF with one
line naming the variable. Nothing is borrowed silently.

**Why.** A community fine-tune may ship a different vision tower; pairing it with the base model's
projector is a guess dressed as a default. The operator's own deployment is the place to make that
claim, and it is the only place that knows what the pack is.

**Evidence — this was MEASURED, not assumed.** On the live `strata/sc117` deployment (the ORCA
uncensored IQ3_XXS community pack, launched entirely through `STRATA_RUN_ARGS`), the base model's
BF16 encoder was named explicitly via `VISION_MMPROJ_URL` and the engine read pictures correctly
three times out of three on distinct solid-colour PNGs — `Red`, `Blue`, `Green` — in 0.5–0.7 s each,
CPU reader, 8 threads, after `strata-vision: model files loaded in 0.5 s`. So the override path is
proven end to end on a real community pack; the DEFAULT for an unknown family stays off.

**Control.** The pass's `family ... ships no image encoder upstream` line, and the fact that the
`check-strata-gpu-pod` bed (a menu model) needs no override at all.

**Invalidated by.** Upstream publishing an encoder per community pack, or a pack declaring its own
`mmproj` in a way the pass can read.

## V8 — The deployment's model choice and env stay LOCAL

**Decision.** This ledger and the PR carry the MECHANISM and the DEFAULT. No deployment's model, pack,
encoder path or overlay is committed here.

**Why.** Operator instruction for this change ("keep the actual deployment config and model choice
local"). It is also the family's standing rule: a concrete model's paths are the deployment's
business.

**Evidence.** The local trial's settings live in the operator's own `~/.config/charly/charly.yml`
(`strata/sc117`: `VISION`, `VISION_MMPROJ_URL`, `STRATA_OVERLAY_JSON`) and in the volume's run config —
neither is in this repo.

**Control.** The PR's diff contains no deployment file; the bed uses the candy default.

**Invalidated by.** The operator asking for a documented example deployment in-repo.

---

## V9 — 64K is the default context, and the reserve that makes it safe

**Decision.** `CONTEXT` defaults to `65536`, and `STRATA_RUN_ARGS` defaults to
`--vram-reserve-mib 1024`. A deployment that sets `STRATA_RUN_ARGS` owns the whole string.

**Why.** 64K is what a real agent client needs: one Hermes Agent turn measured **12,060 prompt
tokens** before it did anything (`in=12060 out=1154 total=13214 latency=34.8s`). The engine's own
recommendation for a small card is lower — `own_path_context` returns `32768` at ≤16.5 GB and this
host's card measures `15.9921875` GB — so 64K is a deliberate step up, and it is affordable only
because the KV cache STREAMS to system RAM from 64K up (`kv_streaming_wanted`, which upstream's
setup satisfies by writing `--kv-resident 32768`).

**Evidence (measured live, on the 16 GB card).** The step up has a VRAM cost, and the engine says so
per request (`upstream #2065`): at 64K with the engine's own 700-MiB reserve it reported **413 MiB
free** and asked for 832; at **960** it still measured **509 MiB — 3 MiB under its own 512-MiB
threshold** — and asked for **1024**. At 1024 it reports 673 MiB free at load, the warning stops, and
the run is healthy: `KV streaming: 91.49% of 197184 block reads hit VRAM, 67.6 MiB read from RAM`,
`decode expert cache hit rate: 80.7%`.

That is why the default is **1024 and not 960**: 960 was the number the engine printed for a
shallower configuration, and it does not clear the threshold at the default context. The number is
the engine's own, not a preference — a deployment with a 24 GB+ card may lower it.

**Scope, stated on purpose.** `CONTEXT` is an INSTALL-TIME choice: it becomes the run config's
`--max-context`, and an installed config keeps its recorded value. So a NEW deployment gets 64K from
this default, while an EXISTING one moves with `STRATA_RUN_ARGS` (`--max-context 65536 --kv-resident
32768`). This asymmetry with `VISION` (`V2`, applied every start) is deliberate: `VISION` had NO
reachable surface at all on an installed model, whereas the context has a documented live one, and a
default that silently rewrote an operator's chosen context would be the bug, not the fix.

**Control.** The bed pins `CONTEXT: "65536"` and asserts `/health` reports it back — a value that
differs from the engine's 32768 recommendation for that card, so the assertion can actually fail.
Measured live after the change: `/health` → `"max_context": 65536`.

**Invalidated by.** Upstream moving the 512-MiB threshold or the `own_path_context` brackets, or the
KV streaming rule — re-measure the warning sequence rather than trusting these numbers.

---

## O1 — OPEN: the cited D-ledger is absent from `origin/main`

`AGENTS.md`, the candy comments and this repo's history cite `opencharly/opencharly`,
`plan/strata-layer-and-pod.md`, entries **D1–D16** (and section numbers like §4.8, §5.2.1, §89, §94).
That file is **not** in `opencharly/opencharly`'s `origin/main`, and no path in that repo's tree
contains "strata":

```
git -C opencharly/opencharly ls-tree -r --name-only origin/main | grep -i strata   # → (nothing)
```

So every D-number in this family currently resolves to nothing. That is recorded here rather than
silently re-invented: the missing entries were NOT reconstructed from their citations, because
reconstructing a decision record from references to it produces fiction with authority.

**Filed: opencharly/opencharly#556** — asking the owning repo either to restore the document (it
evidently exists off-repo, in a session plan directory) or to confirm it was retired, so this family
can drop the citations in one pass and re-home the decisions it still depends on (the bake, the
host-path store, the overlay mechanism, the `SETUP_OWNED` rule) here. Until one of those happens, this
file is the resolvable record for the vision change, and `V*` ids are used deliberately so they cannot
be confused with D*.

---

## How this change is gated

1. **Build context, GPU-free, deterministic** — `charly box validate`, then the candy's own checks:
   the encoder binary and its stamp (`V5`), the table against upstream (`V6`), and the pass itself on
   a synthetic config (`V1`, `V2`, `V4`).
2. **A live deployment** — the operator-directed gate for this change: the new image runs on the
   local `strata/sc117` deployment, the vision pass (not a hand edit) writes the section, and a real
   picture round-trips.
3. **`check-strata-gpu-pod`** — the family's own bed, updated to assert pictures-on from the DEFAULT,
   the section on the volume, `lazy_load` reconciled, and one real picture round-trip.

Every one of those fails on the pre-change tree; the pass does not exist there.
