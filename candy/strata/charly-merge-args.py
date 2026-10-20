#!/usr/bin/env python3
"""Merge a deployment-supplied extra engine argv into a Strata run config's `args`.

The engine's argv is the run config's `args`, which `setup.py` records and
``charly-merge-config.py`` refuses by design (it is a setup-owned key).  A model outside
setup.py's model menu -- a community pack with its own ``--pack``, ``--native``,
``--ple-gguf`` and ``--mtp`` -- therefore has no charly surface unless the entrypoint can
write that argv.  This helper is that explicit write path: the deployment sets
``STRATA_RUN_ARGS``, and every flag it names has its value REPLACED in place (or is
appended when absent).  Empty is a no-op.

Usage: charly-merge-args.py <config.json> <extra-args-string>

The string is shell-split (``shlex.split``), so a path with spaces is quoted as usual.
Only ``--flag`` tokens are accepted; a token that is not a flag and not the value of one
is a hard error (a named failure, never a silent no-op).  The write is atomic and keeps
the engine's own ``.bak`` convention.
"""

import json
import os
import shlex
import sys
import tempfile
from pathlib import Path


def merge(config_path: Path, extra: str) -> int:
    cfg = json.loads(config_path.read_text())
    args = list(cfg.get("args") or [])
    tokens = shlex.split(extra)
    if not tokens:
        print("[charly] STRATA_RUN_ARGS is empty; nothing to merge", flush=True)
        return 0

    changes: list[str] = []
    i = 0
    while i < len(tokens):
        flag = tokens[i]
        if not flag.startswith("--"):
            sys.exit(f"charly-merge-args: expected a --flag, got {flag!r}")
        value = None
        if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
            value = tokens[i + 1]
            i += 2
        else:
            i += 1
        pair = [flag] + ([value] if value is not None else [])

        if flag in args:
            j = args.index(flag)
            has_value = j + 1 < len(args) and not args[j + 1].startswith("--")
            old = args[j:j + (2 if has_value else 1)]
            if old != pair:
                args[j:j + len(old)] = pair
                changes.append(flag)
        else:
            args.extend(pair)
            changes.append(flag)

    if not changes:
        print("[charly] STRATA_RUN_ARGS already in effect; nothing to write", flush=True)
        return 0

    cfg["args"] = args
    tmp_fd, tmp_name = tempfile.mkstemp(dir=str(config_path.parent), prefix=config_path.name + ".")
    try:
        with os.fdopen(tmp_fd, "w") as handle:
            json.dump(cfg, handle, indent=1)
            handle.write("\n")
        bak = config_path.with_name(config_path.name + ".bak")
        try:
            os.replace(config_path, bak)
        except OSError:
            pass  # a missing .bak is cosmetic; the config itself is what matters
        os.replace(tmp_name, config_path)  # atomic: same directory, same filesystem
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    print(f"[charly] STRATA_RUN_ARGS applied to {config_path.name}: {', '.join(changes)}", flush=True)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} <config.json> <extra-args>", file=sys.stderr)
        return 64
    config_path = Path(argv[1])
    if not config_path.is_file():
        print(f"[charly] no run config at {config_path} yet; nothing to merge", flush=True)
        return 0
    return merge(config_path, argv[2])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
