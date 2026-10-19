#!/bin/sh
# charly-owned entrypoint — mechanism (a) of ledger D12.
#
#   env -> (optional install pass) -> overlay merge into the VOLUME config -> upstream's launch
#
# Why a wrapper at all: upstream's `docker-entrypoint.sh` does the install pass and the launch, but
# the run config only comes into existence *during* that pass, so a charly-authored overlay cannot be
# merged before it and the *load-time* keys (parallel, replicas, mcp_servers, min_free_vram_mib ...)
# cannot come from `POST /config` -- measured: the engine refuses them with invalid_request_error.
# So this wrapper reuses upstream's documented argv (never its internals) and inserts the one merge
# step between the pass and the launch. It stays thin on purpose: setup.py remains the only thing
# that builds the pack, writes the config's recorded keys and starts the server.
#
# It also implements the GPU-free `--engine mock` posture (ledger D7), which is what lets the
# deterministic roster bed prove the image, the service, the port and the config projection with no
# card and no model -- upstream ships that mode as "a scripted engine, for clients and tests".

set -eu

cd /opt/strata || exit 1

: "${STRATA_DATA:=/data}"
: "${PORT:=8080}"
: "${HOST:=0.0.0.0}"
: "${FAMILY:=qwen}"
: "${MODEL:=IQ2_XS}"
: "${CONTEXT:=32768}"
: "${VISION:=no}"
: "${LOW_RAM:=auto}"
: "${STRATA_OVERLAY:=/opt/strata/charly-overlay.json}"

# The candy declares the secret as STRATA_API_KEY (a valid env-var name, which the schema requires);
# upstream's contract reads API_KEY. One projection, no renaming of Strata's own variables.
if [ -n "${STRATA_API_KEY:-}" ] && [ -z "${API_KEY:-}" ]; then
    API_KEY="$STRATA_API_KEY"
fi
export STRATA_DATA PORT HOST FAMILY MODEL CONTEXT VISION LOW_RAM
export API_KEY="${API_KEY:-}"

# The API key is OPTIONAL: a local deployment leaves STRATA_API_KEY out entirely and the engine
# then serves openly. The engine REJECTS an empty --api-key as malformed ("an API key was given
# but it is empty"), so the flag is emitted ONLY when a key exists -- measured.
API_KEY_ARG=""
if [ -n "${API_KEY:-}" ]; then API_KEY_ARG="--api-key $API_KEY"; fi

# --- the deterministic, GPU-free posture (D7) ------------------------------------------------
if [ "${STRATA_ENGINE:-strata}" = "mock" ]; then
    echo "[charly] starting the scripted engine: no GPU, no model, no config" >&2
    # The key has to reach the mock too. Without it /health reports api_key:false and the
    # deterministic bed cannot prove the /v1/* gate at all -- measured: with --api-key the gate
    # answers 401 without a key and 200 with one, and /health reports api_key:true.
    if [ -n "$API_KEY" ]; then
        exec .venv/bin/python -m serve.server --engine mock --host "$HOST" --port "$PORT" $API_KEY_ARG
    fi
    exec .venv/bin/python -m serve.server --engine mock --host "$HOST" --port "$PORT"
fi

# --- the run config's identity (upstream's own tag rule: family prefix + lowercased model) ---
case "$FAMILY" in
    qwen) tag_prefix="" ;;
    *)    tag_prefix="$FAMILY-" ;;
esac
tag="${tag_prefix}$(printf '%s' "$MODEL" | tr 'A-Z' 'a-z')"
cfg="$STRATA_DATA/config/strata-$tag.json"
link="/opt/strata/strata-$tag.json"
mkdir -p "$STRATA_DATA/config"

# --- seed the baked config BEFORE deciding whether to install --------------------------------
# The image is baked, so the config it needs must be baked too ($link is that path). Without this
# the condition below is true on every fresh volume -- the volume is empty by definition at first
# start -- so a baked image re-runs the installer at every launch, and in a rootless container the
# installer cannot write into /opt/strata/.venv: measured on the GPU bed as
#   PermissionError: '/opt/strata/.venv/.strata-pip.json' -> supervisord FATAL -> no listener.
if [ ! -f "$cfg" ] && [ -f "$link" ]; then
    cp -f "$link" "$cfg" && echo "[charly] config seeded from the baked image: $cfg" >&2
fi

# --- the install pass: upstream's argv verbatim, only when it is genuinely needed ------------
if [ "${REINSTALL:-0}" = "1" ] || [ ! -f "$cfg" ]; then
    if [ -n "${GGUF_DIR:-}" ]; then
        echo "[charly] setting up $tag from the GGUF files in $GGUF_DIR (the engine is in the image)" >&2
    else
        echo "[charly] setting up $tag: downloading the model (~70 GB; the engine is in the image)" >&2
    fi
    set -- --family "$FAMILY" --model "$MODEL" --context "$CONTEXT" --vision "$VISION" \
        --data-dir "$STRATA_DATA" --host "$HOST" $API_KEY_ARG \
        --port "$PORT" --no-start --low-ram "$LOW_RAM"
    # Each of these is passed ONLY when set, so an unset one keeps setup.py's own default.
    if [ -n "${KV:-}" ]; then set -- "$@" --kv "$KV"; fi
    if [ -n "${GPUS:-}" ]; then set -- "$@" --gpus "$GPUS"; fi
    if [ -n "${GPU:-}" ]; then set -- "$@" --gpu "$GPU"; fi
    if [ -n "${LAYER_SPLIT:-}" ]; then set -- "$@" --layer-split "$LAYER_SPLIT"; fi
    if [ -n "${GGUF_DIR:-}" ]; then set -- "$@" --gguf-dir "$GGUF_DIR"; fi
    if [ -n "${RESIDENT_BUDGET_GIB:-}" ]; then set -- "$@" --resident-budget-gib "$RESIDENT_BUDGET_GIB"; fi
    if [ -n "${KV_STREAMING:-}" ]; then set -- "$@" --kv-streaming "$KV_STREAMING"; fi
    .venv/bin/python setup.py --setup --yes "$@"
    # Upstream leaves its recorded output beside the checkout; the copy on the volume is the one
    # that counts (#1244), so carry it over when the pass produced one.
    if [ -f "$link" ] && [ ! -L "$link" ]; then
        cmp -s "$link" "$cfg" || cp -f "$link" "$cfg"
    fi
    echo "[charly] config: $cfg (just set up)" >&2
else
    echo "[charly] config: $cfg (already installed)" >&2
fi

# --- Layer B: merge the charly overlay into the config on the VOLUME (mechanism (a)) ---------
# Layer B: merge the overlay into the config on the VOLUME (mechanism (a)). The overlay comes from
# STRATA_OVERLAY_JSON when the deployment sets it -- so ANY runtime key is settable from a
# deployment's `env:`, and charly never has to hard-code the engine's key list -- and otherwise from
# the baked file, whose values are the documented defaults.
if [ -f "$cfg" ]; then
    if [ -n "${STRATA_OVERLAY_JSON:-}" ]; then
        python3 /opt/strata/charly-merge-config.py "$cfg" - || {
            echo "[charly] FATAL: STRATA_OVERLAY_JSON could not be merged into $cfg" >&2
            exit 1
        }
    elif [ -f "$STRATA_OVERLAY" ]; then
        python3 /opt/strata/charly-merge-config.py "$cfg" "$STRATA_OVERLAY" || {
            echo "[charly] FATAL: the overlay could not be merged into $cfg" >&2
            exit 1
        }
    fi
fi

# --- Layer C: merge a deployment-supplied extra argv into the config's `args` ------------------
# The engine's argv is the run config's `args`, which setup.py records and the overlay helper
# refuses by design. A model outside setup.py's menu -- a community pack with its own
# --pack/--native/--ple-gguf/--mtp -- is what STRATA_RUN_ARGS exists for: the deployment supplies
# the extra argv and this helper replaces/appends each flag in place. Empty is a no-op.
if [ -f "$cfg" ] && [ -n "${STRATA_RUN_ARGS:-}" ]; then
    python3 /opt/strata/charly-merge-args.py "$cfg" "$STRATA_RUN_ARGS" || {
        echo "[charly] FATAL: STRATA_RUN_ARGS could not be merged into $cfg" >&2
        exit 1
    }
fi

# --- re-assert the documented invariant (#1244) ----------------------------------------------
# The launch below passes --config "$cfg" explicitly, so the server does not read this link. It is
# kept for a settings pass that resolves the image-baked name instead of the volume path.
# /opt/strata is read-only at runtime, measured on the GPU bed:
#     ln: failed to create symbolic link '/opt/strata/strata-iq2_xs.json': Permission denied
# so the invariant is re-asserted only where the image allows it. That is a filesystem property
# test, not a suppressed error: on a writable layer the link is still restored.
if [ -f "$cfg" ] && [ -w "$(dirname "$link")" ]; then
    ln -sfn "$cfg" "$link"
fi

# --- launch -----------------------------------------------------------------------------------
# Serve directly instead of re-entering setup.py. Upstream's setup "installs everything and starts
# the model", but every LATER start "skips straight to running the model" -- which is serve/server.py,
# the invocation run-<model>.sh itself execs. The image is already baked (setup ran at build time), so
# re-entering the installer only buys its preamble: measured on the GPU bed, the checks asked for
# /health 11 s after start while setup was still preparing, and got "connection refused" five times.
# The card pins belong in the config ($cfg, assembled above), not on a command line: server.py does
# not accept --gpus/--gpu/--layer-split.
exec .venv/bin/python serve/server.py --engine strata --config "$cfg" \
    --host "$HOST" --port "$PORT" $API_KEY_ARG
