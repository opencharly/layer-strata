#!/usr/bin/env python3
"""Bake the Strata engine into the image, the way upstream's own Dockerfile does.

Why this exists (ledger D6): upstream publishes **no Linux engine binary** -- all 51 of its
releases carry Windows-only assets -- so on Linux the engine is always compiled. Compiling at
first start would cost 20-40 minutes on every fresh volume. Upstream's Dockerfile solves that by
compiling during the image build and writing ``engine/BUILD.json`` with ``source: "local"`` plus
the hash of the engine sources, which is what ``setup.py`` reads to decide the engine is current:

    "BUILD.json is what setup.py reads to decide whether an engine is current: source=local with a
     matching src hash means the first start reuses it instead of recompiling."

Two properties this script keeps that a naive transcription does not:

1. **The stamp is written LAST**, only after the binaries were produced. Upstream #2054 measured a
   *failed* build leaving ``BUILD.json`` rewritten with the new version and source hash, after
   which every later run reported "engine already built" while the binary stayed stale.
2. **The source tree is never touched.** Any edit changes ``source_hash(ENGINE_SOURCES)`` and
   silently re-triggers a first-start compile, which is the cost this whole file avoids.

The build itself is upstream's code, not a reimplementation: ``setup.get_llama_cpp()``,
``setup.find_nvcc()`` and ``setup.cmake_build()`` are the same three calls the Dockerfile makes,
with the same flags.
"""

import json
import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path("/opt/strata")
sys.path.insert(0, str(ROOT))

import setup  # noqa: E402  (upstream's installer module, imported for its build functions)


def _archs() -> str:
    """The CUDA architecture list, as a Docker ARG equivalent.

    ``docker build`` has no GPU, so the list is fixed here rather than read from nvidia-smi; the
    engine is a fat binary with a cubin per listed architecture and the runtime picks the one that
    matches the card. ``CMakeLists`` refuses anything below 75. A card outside the set needs a
    rebuild with its own architecture -- the box narrows this list per image.
    """
    raw = os.environ.get("STRATA_CUDA_ARCHS", "75;80;86;89;120")
    return raw.strip().strip('"').replace(",", ";")


def main() -> int:
    arch = _archs()
    vision = "gpu" if os.environ.get("STRATA_BUILD_VISION", "1") == "1" else "none"
    isa_floor = os.environ.get("STRATA_ISA_FLOOR", "").strip()
    if isa_floor:
        # An older CPU needs a differently compiled engine; setup.py reads this itself, so it only
        # has to be exported for the build below.
        os.environ["STRATA_ISA_FLOOR"] = isa_floor
        print(f"[charly] engine ISA floor: {isa_floor}", flush=True)

    print(f"[charly] baking the engine for CUDA architectures {arch} (vision={vision})", flush=True)

    llama = setup.get_llama_cpp()          # the pinned LLAMA_CPP_COMMIT, fetched into third_party/
    nvcc, _ = setup.find_nvcc()            # the toolkit the locked CachyOS base provides
    # Hand CMake the toolkit's REAL compiler binary, not the stitched one.
    #
    # CMake derives the CUDA toolkit ROOT from the COMPILER'S PATH, then passes that root's include
    # directory as `-isystem` *before* the C++ standard include directory. The `cuda` candy stitches
    # the toolkit into /usr, so resolving nvcc through the stitched path made the derived root `/usr`
    # and CMake emitted `-isystem /usr/include` -- the very directory that holds glibc's `math.h`.
    # `cmath` pulls that header in with `#include_next`, which means "resume searching AFTER the
    # directory you found me in"; /usr/include had already been passed, so `math.h` became
    # unreachable and every CUDA compile died with
    # `/usr/include/c++/16/cmath:55:15: fatal error: math.h: No such file or directory`.
    # The real path keeps the canonical /usr identity for consumers while making the derived root
    # /opt/cuda, whose include dir collides with nothing.
    _real_nvcc = pathlib.Path("/opt/cuda/bin/nvcc")
    if _real_nvcc.is_file():
        nvcc = str(_real_nvcc)
    print(f"[charly] llama.cpp at {llama}; nvcc at {nvcc}", flush=True)

    setup.cmake_build(
        ROOT, ROOT / "build", "strata",
        ["-DSTRATA_ENABLE_CUDA=ON",
         "-DSTRATA_BUILD_TESTS=OFF",
         f"-DCMAKE_CUDA_ARCHITECTURES={arch}",
         f"-DCMAKE_CUDA_COMPILER={nvcc}",
         f"-DSTRATA_GGML_DIR={llama}"],
        None, "build-strata.bat",
    )
    if vision != "none":
        setup.cmake_build(
            ROOT / "tools" / "vision", ROOT / "build-vision", "strata-vision",
            [f"-DLLAMA_DIR={llama}", "-DSTRATA_VISION_CUDA=ON", "-DSTRATA_PORTABLE=OFF",
             f"-DCMAKE_CUDA_ARCHITECTURES={arch}", f"-DCMAKE_CUDA_COMPILER={nvcc}"],
            None, "build-vision.bat",
        )

    # --- the artifacts ---------------------------------------------------------------------
    # Nothing above here has touched engine/, so a failure leaves no stamp to lie about.
    eng = ROOT / "engine"
    eng.mkdir(exist_ok=True)

    exe_src = ROOT / "build" / setup.EXE
    if not exe_src.is_file():
        print(f"[charly] FATAL: the build produced no {exe_src}", file=sys.stderr)
        return 1
    shutil.copy2(exe_src, eng / setup.EXE)

    # The K-quant MMQ prompt library for the Unsloth UD-Q4/Q5/Q6_K_XL files. It is optional for a
    # model without those experts, so its absence is not a failure -- but it must be carried when
    # the build produced it, or MTP/K-quant prompts silently fall back to the FP16 path.
    if (ROOT / "build" / setup.KQ_LIB).exists():
        shutil.copy2(ROOT / "build" / setup.KQ_LIB, eng / setup.KQ_LIB)

    if vision != "none":
        vis = ROOT / "build-vision" / "bin" / setup.VEXE
        if not vis.is_file():
            print(f"[charly] FATAL: vision requested but {vis} was not produced", file=sys.stderr)
            return 1
        shutil.copy2(vis, eng / setup.VEXE)

    # --- the stamp, LAST ---------------------------------------------------------------------
    bindir = pathlib.Path(nvcc).parent
    meta = {
        "source": "local",
        # `backend` is upstream's own stamp field (its AMD path reads meta.get("backend") == "hip").
        # Stating "cuda" is truthful and keeps the stamp self-describing; the CUDA reader
        # (engine_archs) does not consult it today.
        "backend": "cuda",
        "version": setup.source_version(),
        "archs": [int(a.split("-")[0]) for a in arch.split(";") if a.split("-")[0].isdigit()],
        "vision": vision,
        "cuda_dirs": [str(d) for d in (bindir, bindir / "x64", bindir.parent / "lib64") if d.is_dir()],
        "src": setup.source_hash(setup.ENGINE_SOURCES),
        "vision_src": setup.source_hash(setup.VISION_SOURCES) if vision != "none" else None,
    }
    # NOTE -- `ptx` is deliberately NOT written. The reader is
    #     archs, ptx = [int(x) for x in meta.get("archs", [])], bool(meta.get("ptx"))
    # so an absent `ptx` means "this engine has no JIT fallback", which is TRUE for a build whose
    # CMAKE_CUDA_ARCHITECTURES is a plain SASS list. Writing `ptx: true` to look more like a release
    # stamp would be a stamp that lies about the artifact -- the exact failure upstream #2054 measured,
    # and the reason this whole file writes the stamp LAST. A card outside `archs` needs a rebuild that
    # includes its architecture (what the fat default is for); it does not need a fabricated capability.
    (eng / "BUILD.json").write_text(json.dumps(meta, indent=1))
    print(f"[charly] engine stamped: {json.dumps(meta)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
