#!/usr/bin/env python3
"""Apply the deployment's `VISION` to a Strata run config that already exists.

Why this file exists (ledger V2/V3, `LEDGER.md`): upstream writes the run config's ``"vision"``
section in ``setup.py``, and ``setup.py`` runs only when the config is ABSENT (or ``REINSTALL=1``).
Every other start -- a restart, a redeploy, any community pack launched through ``STRATA_RUN_ARGS``
-- therefore never sees ``VISION`` at all: the section is never written, ``/health`` keeps answering
``"images": false``, and nothing reports the knob was ignored. The Layer-B overlay cannot carry it
either, because ``"vision"`` is ``SETUP_OWNED`` and the merge helper refuses those by design.

So this helper is the ONE writer of the section on an installed config, and it follows the same two
rules the merge helpers follow: an atomic, key-wise write that keeps the engine's own formatting and
``.bak`` convention, and a hard error -- never a silent no-op -- when the request cannot be honoured
honestly.

Three things it owns, and why each is here rather than in a config file:

* **The section.** ``setup.py``'s own shape: ``exe``, ``mmproj``, ``model``, ``gpu``, ``max_tokens``,
  ``threads``. ``model`` is the text model the encoder opens vocab-only, and every run config carries
  it as the value after ``--native`` -- true for a setup-installed model AND for a community pack.
* **The encoder file.** It is MODEL DATA (0.9 GB, licensed with the weights), so it is downloaded
  once into the model store and reused; it never enters the image. The SOFTWARE around it -- the
  ``strata-vision`` binary -- IS in the image, baked by ``charly-build-engine.py``.
* **The ``lazy_load`` pair.** Upstream's settings validator REFUSES to set ``lazy_load: true`` on a
  config that reads images (``serve/runconfig.py:92``, and ``:126`` is that validator's only call
  site -- the settings-write path), and upstream documents the key as "text only" (``:33``). The
  startup path (``load()``, ``:175``) does NOT validate the pair: measured, the engine starts with
  both and reports ``images: true``. So this is not crash-prevention -- it is contract alignment:
  charly does not manufacture a configuration upstream's own API refuses to write. It is settled
  here, last, and says so in one line.

Degradation is deliberate and loud, never silent: a deployment that asked for pictures and cannot
get them (no encoder for its family, no network) still SERVES TEXT and prints exactly one line
saying so -- upstream's own posture ("where a reader is missing, pictures stay off and the screen
says so"). Upstream's engine does the same when its encoder fails to start.

Values of ``VISION`` (the candy's documented surface, `VISION` in candy/strata/charly.yml):
``cpu`` (default) reads pictures on the CPU; ``gpu`` reads them on the card; ``no``/``off`` turns
them off. ``yes``/``on`` are accepted as aliases for ``cpu`` and say so: at the pinned tag upstream
maps ``--vision yes`` to the GPU reader, and this family deliberately does not, because the expert
cache already runs VRAM-tight and upstream measured the card's reader SLOWER for text on a 16 GB
card. A deployment that wants the card's reader asks for it by name.
"""

import json
import os
import pathlib
import socket
import sys
import tempfile
import urllib.error
import urllib.request

# Setup-choice defaults. These are DEFAULTS a deployment overrides through its `env:`; the candy's
# `var:` block carries the same values, and neither renames anything upstream.
DEFAULT_DATA = "/data"
ENGINE_DIR = "/opt/strata/engine"
VISION_EXE = ENGINE_DIR + "/strata-vision"
TEXT_MODEL_FLAG = "--native"
GGUF_MAGIC = b"GGUF"
DOWNLOAD_TIMEOUT_S = 120
# Upstream's per-device defaults (`VISION` in setup.py at the pin): the most image tokens a picture
# becomes, and the reader's reserve. A CPU picture is smaller by default because encoding time grows
# with image tokens and the CPU has no faster path.
DEVICE_DEFAULTS = {"cpu": {"max_tokens": 300}, "gpu": {"max_tokens": 1024}}

# The family -> encoder table, mirroring upstream `setup.py`'s FAMILIES entries AT THE PIN
# (v0.1.44.1), revision-pinned exactly as `hf()` builds them. It is DATA, not a rule: the candy's
# build-context check `strata-vision-table` asserts every row equals `setup.FAMILIES[family]` inside
# the built image, so a repin cannot let this drift silently (ledger V6). `qwen36` is listed as
# ENCODER-LESS because upstream declares `"vision": False` for it: its encoder is not wired up.
#
# A family that is absent here is not an error -- it means upstream ships no encoder this helper can
# name, so the deployment must name its own file (`VISION_MMPROJ_URL`); that is the community-pack
# case, which is validated rather than assumed (ledger V7).
FAMILIES = {
    "qwen": {
        "url": "https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF"
               "/resolve/ed59f92082b1e93c0e96d60a8b11aab089b52f09/",
        "file": "mmproj-Qwen3.8-Flash-Next-BF16.gguf",
    },
    "swift": {
        "url": "https://huggingface.co/ukisai/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF"
               "/resolve/b22d729eae29b5796f76fb70f91aef549b9fc52c/",
        "file": "mmproj-Swift-Qwen3.8-Flash-Next-BF16.gguf",
    },
    "coder": {
        "url": "https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF"
               "/resolve/5348543e0147355ac9cbcb031184a3546350988e/",
        "file": "mmproj-Qwen3.8-Flash-Next-BF16.gguf",
    },
    "unsloth": {
        "url": "https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF"
               "/resolve/ed59f92082b1e93c0e96d60a8b11aab089b52f09/",
        "file": "mmproj-Qwen3.8-Flash-Next-BF16.gguf",
    },
    "nvfp4": {
        "url": "https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF"
               "/resolve/ed59f92082b1e93c0e96d60a8b11aab089b52f09/",
        "file": "mmproj-Qwen3.8-Flash-Next-BF16.gguf",
    },
    "qwen36": None,   # upstream: "the image encoder for this family is not wired up yet"
}

ON, OFF = "on", "off"


def say(msg):
    print(f"[charly] vision: {msg}", flush=True)


def fatal(msg):
    print(f"[charly] vision: FATAL: {msg}", file=sys.stderr, flush=True)
    return 2


def requested_mode(raw):
    """`VISION` -> ("on", "cpu"|"gpu") | ("off", None) | raise ValueError.

    `yes`/`on` resolve to the CPU reader HERE, and say so -- see the module docstring.
    """
    value = (raw or "cpu").strip().lower()
    if value in ("no", "off", "none", "false", "0"):
        return OFF, None
    if value in ("cpu",):
        return ON, "cpu"
    if value in ("gpu",):
        return ON, "gpu"
    if value in ("yes", "on", "true", "1"):
        say("VISION=" + value + " resolves to the CPU reader (this family's default); "
            "set VISION=gpu to read pictures on the card instead")
        return ON, "cpu"
    raise ValueError(f"VISION={raw!r} is not one of cpu, gpu, no/off (yes/on = cpu)")


def text_model(cfg):
    """The GGUF the encoder opens vocab-only: the value after `--native` in the config's argv.

    Uniform across both model kinds this layer serves -- measured on a setup-installed menu model
    (`--native /data/models/IQ2_XS/...-00001-of-00002.gguf`) and on the community pack
    (`--native /data/orca-download/...-00001-of-00002.gguf`).
    """
    args = cfg.get("args") or []
    for i, arg in enumerate(args[:-1]):
        if arg == TEXT_MODEL_FLAG:
            return args[i + 1]
    return None


def encoder_for(family, override_url, override_file):
    """(url, file) for this family, or (None, None) when it has to be named by the deployment."""
    if override_url:
        name = override_file or (override_url.rstrip("/").rsplit("/", 1)[-1])
        return override_url, name
    entry = FAMILIES.get((family or "qwen").strip().lower())
    if not entry:
        return None, None
    return entry["url"] + entry["file"], entry["file"]


def looks_like_encoder(path):
    """A complete encoder file: present, non-empty, and a GGUF.

    The magic is the cheap integrity check that catches the realistic failure -- an interrupted
    download left a truncated file, which an encoder would then refuse to load at every start.
    """
    try:
        if path.stat().st_size < 1024:
            return False
        with path.open("rb") as handle:
            return handle.read(4) == GGUF_MAGIC
    except OSError:
        return False


def fetch(url, dest):
    """Download `url` to `dest` atomically; return True on success.

    Verified against the server's own `Content-Length` (no per-family size table to drift) and the
    GGUF magic afterwards. A failure leaves NO partial file behind under the real name -- the `.part`
    file is what a retry resumes from, so a half-written encoder can never be mistaken for a good one.
    """
    part = dest.with_name(dest.name + ".part")
    say(f"fetching the image encoder ({url.rsplit('/', 1)[-1]}) into {dest} -- this happens once")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "charly-strata"})
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as response:
            expected = response.headers.get("Content-Length")
            written = 0
            with part.open("wb") as handle:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    handle.write(chunk)
                    written += len(chunk)
        if expected is not None and int(expected) != written:
            raise OSError(f"short download: {written} of {expected} bytes")
        if not looks_like_encoder(part):
            raise OSError("the downloaded file is not a GGUF encoder")
        os.replace(part, dest)
        say(f"image encoder ready: {dest} ({written / (1 << 20):.0f} MiB)")
        return True
    except (OSError, urllib.error.URLError, socket.timeout) as exc:
        try:
            part.unlink()
        except OSError:
            pass
        say(f"could not fetch the image encoder ({exc}); pictures stay off, the server serves text")
        return False


def ensure_encoder(dest, url):
    """True when a usable encoder is at `dest` -- reusing what a previous start left there."""
    if looks_like_encoder(dest):
        say(f"reusing the image encoder already in the store: {dest}")
        return True
    return fetch(url, dest)


def write_config(config_path, cfg):
    """Atomic, key-wise write keeping the engine's own conventions (indent=1, `<name>.bak`)."""
    payload = json.dumps(cfg, indent=1) + "\n"
    if payload == config_path.read_text():
        return False
    handle, tmp_name = tempfile.mkstemp(dir=str(config_path.parent), prefix=config_path.name + ".")
    try:
        with os.fdopen(handle, "w") as out:
            out.write(payload)
        if config_path.exists():
            try:
                os.replace(config_path, config_path.with_name(config_path.name + ".bak"))
            except OSError:
                pass   # a missing .bak is cosmetic; the config itself is what matters
        os.replace(tmp_name, config_path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return True


def desired_section(device, mmproj_path, model_path, threads, tokens):
    section = {
        "exe": VISION_EXE,
        "mmproj": mmproj_path,
        "model": model_path,
        "gpu": device == "gpu",
        "max_tokens": tokens,
    }
    # `setup.py` writes `threads` for the CPU reader only, and never for the card's reader.
    if device == "cpu":
        section["threads"] = threads
    return section


def main(argv):
    if len(argv) != 2:
        return fatal(f"usage: {argv[0]} <config.json>")
    config_path = pathlib.Path(argv[1])

    if (os.environ.get("STRATA_ENGINE") or "strata") == "mock":
        # The scripted posture starts with no run config at all; there is nothing to apply.
        return 0
    if not config_path.is_file():
        # A config that does not exist yet is the installer's: setup.py writes the section itself.
        say(f"no run config at {config_path} yet; nothing to apply")
        return 0

    try:
        cfg = json.loads(config_path.read_text())
    except (OSError, ValueError) as exc:
        return fatal(f"{config_path} is not readable JSON: {exc}")

    try:
        mode, device = requested_mode(os.environ.get("VISION"))
    except ValueError as exc:
        return fatal(str(exc))

    existing = cfg.get("vision") if isinstance(cfg.get("vision"), dict) else None

    if mode == OFF:
        if existing is None:
            say("pictures are off (VISION=no) and the config carries no vision section; nothing to do")
            return 0
        cfg.pop("vision")
        # `lazy_load` is NOT re-enabled here: whether it is true is the deployment's business, and the
        # server only refuses the PAIR.
        write_config(config_path, cfg)
        say(f"pictures off: removed the vision section from {config_path.name} (engine reads text only)")
        return 0

    model_path = text_model(cfg)
    if not model_path:
        say("this run config has no " + TEXT_MODEL_FLAG + " in its args, so the encoder has no text "
            "model to open; pictures stay off, the server serves text")
        return 0

    url, name = encoder_for(os.environ.get("FAMILY"), os.environ.get("VISION_MMPROJ_URL"),
                            os.environ.get("VISION_MMPROJ"))
    if not url:
        family = os.environ.get("FAMILY") or "qwen"
        say(f"family {family!r} ships no image encoder upstream, and no VISION_MMPROJ_URL names one; "
            "pictures stay off. Set VISION_MMPROJ_URL to this model's own mmproj file to turn them on")
        return 0

    data_dir = pathlib.Path(os.environ.get("STRATA_DATA") or DEFAULT_DATA)
    mmproj_path = data_dir / "vision" / name
    mmproj_path.parent.mkdir(parents=True, exist_ok=True)
    if not ensure_encoder(mmproj_path, url):
        return 0

    try:
        threads = int(os.environ.get("VISION_THREADS") or 0)
    except ValueError:
        return fatal(f"VISION_THREADS={os.environ.get('VISION_THREADS')!r} is not an integer")
    if threads <= 0:
        threads = max(1, (os.cpu_count() or 8) // 2)    # upstream's own rule for the CPU reader
    try:
        tokens = int(os.environ.get("VISION_TOKENS") or 0)
    except ValueError:
        return fatal(f"VISION_TOKENS={os.environ.get('VISION_TOKENS')!r} is not an integer")
    if tokens <= 0:
        tokens = DEVICE_DEFAULTS[device]["max_tokens"]

    wanted = desired_section(device, str(mmproj_path), model_path, threads, tokens)
    if existing and existing.get("model"):
        # A section setup.py wrote itself is upstream's business: it names the file the encoder opens
        # (`shards[0]` for a GGUF model, `ready_paths(...)["dense"]` for a ready-made pack), and this
        # pass has no evidence to prefer `--native` over it. Keep upstream's choice and only own the
        # keys the deployment's `env:` actually controls.
        wanted["model"] = existing["model"]
    lazy_conflict = cfg.get("lazy_load") is True
    if existing == wanted and not lazy_conflict:
        say(f"already in effect in {config_path.name}; nothing to write")
        return 0

    cfg["vision"] = wanted
    if lazy_conflict:
        # Not a preference: upstream's settings validator refuses to set `lazy_load: true` on a config
        # that reads images (serve/runconfig.py:92), so leaving it would manufacture a config upstream's
        # own API refuses to write. The load path tolerates it today (measured), which is why this is
        # contract alignment and not crash-prevention -- see the module docstring.
        cfg["lazy_load"] = False
        say("lazy_load was true beside a vision section (upstream's settings validator refuses that "
            "pair): set to false, so the model loads at start instead of on the first request")
    write_config(config_path, cfg)
    reader = "the card" if device == "gpu" else f"the CPU, {threads} threads"
    say(f"pictures on: {config_path.name} now carries a vision section (reader: {reader}, "
        f"up to {tokens} image tokens per picture) -- the engine loads the encoder beside the model")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
