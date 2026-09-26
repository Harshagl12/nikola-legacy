"""Local CPU/runtime compatibility detection for the bundled llama.cpp path."""

from __future__ import annotations

import platform
import re
from pathlib import Path
from typing import Any


FEATURE_NAMES = ("AVX", "AVX2", "FMA", "F16C")


def detect_cpu_features() -> dict[str, bool]:
    """Read CPU feature flags from NumPy's runtime CPUID detection."""
    try:
        from numpy._core._multiarray_umath import __cpu_features__
    except ImportError:
        try:
            from numpy.core._multiarray_umath import __cpu_features__
        except ImportError:
            return {name: False for name in FEATURE_NAMES}

    return {
        "AVX": bool(__cpu_features__.get("AVX")),
        "AVX2": bool(__cpu_features__.get("AVX2")),
        "FMA": bool(__cpu_features__.get("FMA3") or __cpu_features__.get("FMA")),
        "F16C": bool(__cpu_features__.get("F16C")),
    }


def supports_avx512() -> bool:
    try:
        from numpy._core._multiarray_umath import __cpu_features__
    except ImportError:
        try:
            from numpy.core._multiarray_umath import __cpu_features__
        except ImportError:
            return False
    return bool(__cpu_features__.get("AVX512F"))


def runtime_requirements(system_info: str) -> dict[str, bool]:
    """Parse llama.cpp's reported compile-time CPU requirements."""
    return {
        name: bool(re.search(rf"\b{name}\s*=\s*1\b", system_info))
        for name in ("AVX", "AVX2", "FMA", "F16C", "AVX512")
    }


def select_bundled_runtime(root: str | Path) -> dict[str, Any]:
    """Select an existing AVX2 or generic llama-server binary, if bundled."""
    root_path = Path(root).resolve()
    cpu = detect_cpu_features()
    cpu["AVX512"] = supports_avx512()
    variant = "avx2" if cpu["AVX2"] else "generic"
    variant_candidates = (
        root_path / "backend" / "tools" / f"llama-{variant}" / "llama-server.exe",
        root_path / "backend" / "tools" / f"llama-server-{variant}.exe",
        root_path / "backend" / "tools" / "llama-server.exe",
    )
    candidates = variant_candidates
    runtime_path = next((path for path in candidates if path.is_file()), None)
    return {
        "cpu": cpu,
        "variant": variant,
        "path": str(runtime_path) if runtime_path else None,
        "status": "available" if runtime_path else "missing_runtime",
        "cpu_model": platform.processor(),
    }
