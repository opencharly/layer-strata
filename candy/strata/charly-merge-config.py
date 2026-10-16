#!/usr/bin/env python3
"""Merge charly's server-behaviour overlay into a Strata run config, key-wise and atomically.

This is mechanism (a) of ledger D12 -- the only write path that can carry Strata's **load-time**
keys. Measured on 2026-10-16: ``POST /config`` refuses them

    {"error": {"type": "invalid_request_error",
               "message": "'parallel' cannot be changed here (only the keys the Settings view lists)"}}

and, in the container, it is worse than useless at our pin: the run config is a **symlink into the
volume** and a save ``os.replace``s the temp file over the link, replacing it with a regular file
inside the image -- so the volume's file never changes and the edit dies with the container
(upstream #2547, still open; verified absent from v0.1.44.1 in the ledger, §2.14.1).

Two rules make this safe:

* **Only setup-PRESERVED keys may be overlaid.** ``setup.py`` rewrites its own ``SETUP_KEYS`` on
  every settings pass, so writing one of those is either pointless or actively harmful; the
  entrypoint's own words are that the config is "the recorded output of that setup ... not settings
  the entry point could rebuild from env vars" (ledger D11). A setup-owned key in the overlay is a
  hard error here rather than a silent no-op.
* **Atomic, key-wise upsert**, keeping every other key, the file's formatting style and the
  ``.bak`` convention the engine itself uses.
"""

import json
import os
import pathlib
import sys
import tempfile

# setup.py's SETUP_KEYS: the keys setup WRITES and rewrites. Overlaying any of them would be
# overwritten by the next settings pass, so this file refuses them (D11).
SETUP_OWNED = {
    "exe", "args", "cwd", "tokenizer", "model_name", "log", "lib_dirs", "port", "backend",
    "env", "gpu", "gpus_asked", "layer_split", "host", "api_key", "draft_vocab", "vision",
    "arch", "cuda",
}

# One level of nesting is merged key-wise (``sampling`` is an object of numbers); everything else is
# replaced wholesale, because that is what Strata's own config reader does with these keys.
NESTED = {"sampling"}


def merge(config_path: pathlib.Path, overlay_path: pathlib.Path) -> int:
    cfg = json.loads(config_path.read_text())
    overlay = json.loads(overlay_path.read_text())

    offenders = sorted(k for k in overlay if k in SETUP_OWNED)
    if offenders:
        print(
            "[charly] refusing to overlay setup-owned key(s): "
            + ", ".join(offenders)
            + " -- setup rewrites those on every settings pass (ledger D11). "
              "Drive them through the deployment's env: instead.",
            file=sys.stderr,
        )
        return 2

    changed = []
    for key, value in overlay.items():
        if key in NESTED and isinstance(value, dict) and isinstance(cfg.get(key), dict):
            for sub, subvalue in value.items():
                if cfg[key].get(sub) != subvalue:
                    cfg[key][sub] = subvalue
                    changed.append(f"{key}.{sub}")
        elif cfg.get(key) != value:
            cfg[key] = value
            changed.append(key)

    if not changed:
        print("[charly] overlay already in effect; nothing to write", flush=True)
        return 0

    # Keep the engine's own conventions: pretty-print, and keep the previous file as <name>.bak.
    tmp_fd, tmp_name = tempfile.mkstemp(dir=str(config_path.parent), prefix=config_path.name + ".")
    try:
        with os.fdopen(tmp_fd, "w") as handle:
            json.dump(cfg, handle, indent=1)
            handle.write("\n")
        if config_path.exists():
            bak = config_path.with_name(config_path.name + ".bak")
            try:
                os.replace(config_path, bak)
            except OSError:
                pass  # a missing .bak is cosmetic; the config itself is what matters
        os.replace(tmp_name, config_path)   # atomic: same directory, so same filesystem
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    print(f"[charly] overlay applied to {config_path.name}: {', '.join(changed)}", flush=True)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} <config.json> <overlay.json|->", file=sys.stderr)
        return 64
    config_path, overlay_arg = pathlib.Path(argv[1]), argv[2]
    if not config_path.is_file():
        print(f"[charly] no run config at {config_path} yet; nothing to merge", flush=True)
        return 0

    # "-" means the overlay is in the ENVIRONMENT rather than in a file. That is what makes the
    # whole runtime surface settable from a deployment's `env:` -- charly's configuration surface --
    # instead of only from the baked overlay, which can carry a fixed list and nothing per-deployment.
    # The KEY NAMES are deliberately never enumerated in this repo: the engine publishes its own
    # catalogue from `GET /config`, and a copy here would drift from it. Only the setup-owned rule is
    # enforced, because that one is about ownership, not about which keys exist.
    overlay_path = pathlib.Path(overlay_arg)
    if overlay_arg == "-":
        raw = os.environ.get("STRATA_OVERLAY_JSON", "").strip()
        if not raw:
            print("[charly] STRATA_OVERLAY_JSON is empty; nothing to merge", flush=True)
            return 0
        try:
            json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"[charly] FATAL: STRATA_OVERLAY_JSON is not valid JSON: {exc}", file=sys.stderr)
            return 1
        handle = tempfile.NamedTemporaryFile("w", suffix=".overlay.json", delete=False)
        handle.write(raw)
        handle.close()
        overlay_path = pathlib.Path(handle.name)
    try:
        return merge(config_path, overlay_path)
    except json.JSONDecodeError as exc:
        print(f"[charly] FATAL: {exc}", file=sys.stderr)
        return 1
    finally:
        # An environment-supplied overlay lives in a temp file for the length of ONE merge; remove it,
        # so a container that restarts many times does not accumulate them.
        if overlay_arg == "-" and overlay_path.name.endswith(".overlay.json"):
            try:
                overlay_path.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main(sys.argv))
