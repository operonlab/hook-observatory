"""Hardware profile schema for cross-machine comparison.

Adapted from TurboQuant+ hw_replay.py pattern — dataclasses + JSON serialization,
no external dependencies beyond stdlib.

Usage:
    # Collect local machine profile
    profile = HardwareProfile.collect_local()
    profile.save("~/workshop/outputs/hw-profiles/mac-mini_2026-03-31.json")

    # Load and compare two profiles
    mac = HardwareProfile.from_json("mac-mini_2026-03-31.json")
    win = HardwareProfile.from_json("rtx3090_2026-03-31.json")
    print(compare_profiles(mac, win))
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class GPUInfo:
    """GPU hardware capabilities."""

    name: str = "unknown"
    vram_mb: float = 0.0
    compute_type: str = ""  # "metal", "cuda", "rocm"


@dataclass
class SystemInfo:
    """System hardware specs (no PII)."""

    hostname: str = "unknown"
    platform: str = "unknown"  # darwin, linux, win32
    arch: str = "unknown"  # arm64, x86_64
    cpu_brand: str = "unknown"
    cpu_cores: int = 0
    ram_gb: int = 0
    gpu: GPUInfo = field(default_factory=GPUInfo)


@dataclass
class BenchmarkResult:
    """Single benchmark latency measurement."""

    task_type: str = ""  # "embedding", "rerank", "llm_inference", "capture_enrichment"
    model: str = ""  # "nomic-embed-text", "jina-reranker-v3", etc.
    latency_ms: float = 0.0
    throughput: float = 0.0  # items/sec
    timestamp: str = ""


@dataclass
class HardwareProfile:
    """Complete hardware profile for a machine."""

    system: SystemInfo = field(default_factory=SystemInfo)
    benchmarks: list[BenchmarkResult] = field(default_factory=list)
    collected_at: str = ""

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        """Serialize to pretty-printed JSON."""
        return json.dumps(asdict(self), indent=2)

    def save(self, path: str | Path) -> None:
        """Save profile to a JSON file, creating parent dirs as needed."""
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json())

    @classmethod
    def from_json(cls, path: str | Path) -> HardwareProfile:
        """Load a profile previously saved with save()."""
        data: dict[str, Any] = json.loads(Path(path).expanduser().read_text())
        profile = cls()
        profile.collected_at = data.get("collected_at", "")

        si = data.get("system", {})
        gpu_data = si.get("gpu", {})
        profile.system = SystemInfo(
            hostname=si.get("hostname", "unknown"),
            platform=si.get("platform", "unknown"),
            arch=si.get("arch", "unknown"),
            cpu_brand=si.get("cpu_brand", "unknown"),
            cpu_cores=si.get("cpu_cores", 0),
            ram_gb=si.get("ram_gb", 0),
            gpu=GPUInfo(
                name=gpu_data.get("name", "unknown"),
                vram_mb=gpu_data.get("vram_mb", 0.0),
                compute_type=gpu_data.get("compute_type", ""),
            ),
        )

        for b in data.get("benchmarks", []):
            profile.benchmarks.append(BenchmarkResult(**b))

        return profile

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------

    @classmethod
    def collect_local(cls) -> HardwareProfile:
        """Auto-detect current machine's hardware specs.

        Supports macOS (Apple Silicon + Intel) and Linux.
        GPU detection: Metal on macOS, CUDA on Linux/Windows.
        Falls back gracefully when sysctl / nvidia-smi are unavailable.
        """
        profile = cls()
        profile.collected_at = datetime.now(UTC).isoformat()

        sys_info = SystemInfo()
        sys_info.hostname = platform.node()
        sys_info.platform = sys.platform  # darwin / linux / win32
        sys_info.arch = platform.machine()  # arm64 / x86_64 / AMD64

        _detect_cpu(sys_info)
        _detect_ram(sys_info)
        _detect_gpu(sys_info)

        profile.system = sys_info
        return profile


# ---------------------------------------------------------------------------
# Hardware detection helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], timeout: int = 5) -> str:
    """Run a subprocess, return stdout or empty string on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)  # noqa: S603
        return result.stdout.strip()
    except Exception:
        return ""


def _detect_cpu(info: SystemInfo) -> None:
    if sys.platform == "darwin":
        brand = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if not brand:
            # Apple Silicon — fall back to sysctl hw.model
            brand = _run(["sysctl", "-n", "hw.model"])
        info.cpu_brand = brand or "unknown"

        cores_str = _run(["sysctl", "-n", "hw.logicalcpu"])
        try:
            info.cpu_cores = int(cores_str)
        except ValueError:
            info.cpu_cores = 0
    elif sys.platform.startswith("linux"):
        # Parse /proc/cpuinfo
        try:
            cpuinfo = Path("/proc/cpuinfo").read_text()
            for line in cpuinfo.splitlines():
                if line.startswith("model name"):
                    info.cpu_brand = line.split(":", 1)[-1].strip()
                    break
            info.cpu_cores = cpuinfo.count("processor\t:")
        except OSError:
            pass
    else:
        # Windows or other
        info.cpu_brand = platform.processor()
        try:
            import os

            info.cpu_cores = os.cpu_count() or 0
        except Exception:  # noqa: S110
            pass


def _detect_ram(info: SystemInfo) -> None:
    if sys.platform == "darwin":
        raw = _run(["sysctl", "-n", "hw.memsize"])
        try:
            info.ram_gb = int(raw) // (1024**3)
        except ValueError:
            pass
    elif sys.platform.startswith("linux"):
        try:
            meminfo = Path("/proc/meminfo").read_text()
            for line in meminfo.splitlines():
                if line.startswith("MemTotal"):
                    kb = int(line.split()[1])
                    info.ram_gb = kb // (1024**2)
                    break
        except OSError:
            pass
    else:
        try:
            import ctypes

            status = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory(  # type: ignore[attr-defined]
                ctypes.byref(status)
            )
            info.ram_gb = int(status.value) // (1024**2)
        except Exception:  # noqa: S110
            pass


def _detect_gpu(info: SystemInfo) -> None:
    if sys.platform == "darwin":
        _detect_metal_gpu(info)
    else:
        _detect_cuda_gpu(info)


def _detect_metal_gpu(info: SystemInfo) -> None:
    """Extract GPU info from system_profiler on macOS."""
    raw = _run(
        ["system_profiler", "SPDisplaysDataType", "-json"],
        timeout=10,
    )
    if not raw:
        info.gpu = GPUInfo(compute_type="metal")
        return

    try:
        data = json.loads(raw)
        displays = data.get("SPDisplaysDataType", [])
        if not displays:
            info.gpu = GPUInfo(compute_type="metal")
            return

        gpu_entry = displays[0]
        name = gpu_entry.get("sppci_model", "unknown")
        # VRAM: "8 GB" or "1536 MB" — Apple Silicon often lacks sppci_vram
        # (unified memory), so fall back to total system RAM as GPU-accessible memory.
        vram_str: str = gpu_entry.get("sppci_vram", "")
        if vram_str:
            vram_mb = _parse_vram_mb(vram_str)
        else:
            # Apple Silicon unified memory: entire RAM is GPU-accessible
            vram_mb = info.ram_gb * 1024 if info.ram_gb else 0
        info.gpu = GPUInfo(name=name, vram_mb=vram_mb, compute_type="metal")
    except (json.JSONDecodeError, KeyError, IndexError):
        info.gpu = GPUInfo(compute_type="metal")


def _detect_cuda_gpu(info: SystemInfo) -> None:
    """Extract GPU info via nvidia-smi."""
    raw = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total",
            "--format=csv,noheader,nounits",
        ]
    )
    if not raw:
        info.gpu = GPUInfo()
        return

    parts = raw.split(",", 1)
    name = parts[0].strip() if parts else "unknown"
    vram_mb = 0.0
    if len(parts) > 1:
        try:
            vram_mb = float(parts[1].strip())
        except ValueError:
            pass
    info.gpu = GPUInfo(name=name, vram_mb=vram_mb, compute_type="cuda")


def _parse_vram_mb(vram_str: str) -> float:
    """Parse "8 GB" or "1536 MB" → float MB."""
    parts = vram_str.strip().split()
    if len(parts) < 2:
        return 0.0
    try:
        value = float(parts[0])
        unit = parts[1].upper()
        if unit == "GB":
            return value * 1024
        return value  # assume MB
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def compare_profiles(baseline: HardwareProfile, target: HardwareProfile) -> str:
    """Generate a markdown comparison report for two hardware profiles.

    Compares:
    - Hardware specs (CPU, RAM, GPU)
    - Benchmark latency for matching task_type + model pairs
    - Flags anomalies when target is >2x slower than baseline
    """
    b_name = baseline.system.hostname or baseline.system.cpu_brand
    t_name = target.system.hostname or target.system.cpu_brand

    lines: list[str] = [
        f"# Hardware Comparison: {b_name} vs {t_name}\n",
        f"Baseline collected: `{baseline.collected_at}`  ",
        f"Target collected:   `{target.collected_at}`\n",
    ]

    # --- Hardware specs table ---
    lines.append("## Hardware Specs\n")
    lines.append("| Property | Baseline | Target |")
    lines.append("|----------|----------|--------|")

    hw_rows: list[tuple[str, str, str]] = [
        ("Hostname", baseline.system.hostname, target.system.hostname),
        ("Platform", baseline.system.platform, target.system.platform),
        ("Arch", baseline.system.arch, target.system.arch),
        ("CPU", baseline.system.cpu_brand, target.system.cpu_brand),
        ("CPU Cores", str(baseline.system.cpu_cores), str(target.system.cpu_cores)),
        ("RAM (GB)", str(baseline.system.ram_gb), str(target.system.ram_gb)),
        ("GPU", baseline.system.gpu.name, target.system.gpu.name),
        ("GPU VRAM (MB)", f"{baseline.system.gpu.vram_mb:.0f}", f"{target.system.gpu.vram_mb:.0f}"),
        ("Compute Type", baseline.system.gpu.compute_type, target.system.gpu.compute_type),
    ]
    for prop, bval, tval in hw_rows:
        marker = " **" if bval != tval else ""
        end = "**" if bval != tval else ""
        lines.append(f"| {prop} | {marker}{bval}{end} | {marker}{tval}{end} |")
    lines.append("")

    # --- Benchmark comparison ---
    # Build lookup: (task_type, model) → BenchmarkResult
    b_bench: dict[tuple[str, str], BenchmarkResult] = {
        (r.task_type, r.model): r for r in baseline.benchmarks
    }
    t_bench: dict[tuple[str, str], BenchmarkResult] = {
        (r.task_type, r.model): r for r in target.benchmarks
    }

    common_keys = sorted(set(b_bench.keys()) & set(t_bench.keys()))

    anomalies: list[str] = []

    if common_keys:
        lines.append("## Benchmark Comparison\n")
        lines.append(
            "| Task | Model | Baseline (ms) | Target (ms) | Ratio | Throughput B | Throughput T |"
        )
        lines.append(
            "|------|-------|--------------|------------|-------|-------------|-------------|"
        )

        for key in common_keys:
            br = b_bench[key]
            tr = t_bench[key]
            ratio = tr.latency_ms / br.latency_ms if br.latency_ms > 0 else 0.0
            flag = " ⚠️" if ratio > 2.0 else ("  ✅" if ratio < 0.5 else "")

            lines.append(
                f"| {br.task_type} | {br.model} "
                f"| {br.latency_ms:.1f} | {tr.latency_ms:.1f} "
                f"| {ratio:.2f}x{flag} "
                f"| {br.throughput:.1f}/s | {tr.throughput:.1f}/s |"
            )

            if ratio > 2.0:
                anomalies.append(
                    f"`{br.task_type}/{br.model}`: target is {ratio:.1f}x slower "
                    f"({tr.latency_ms:.1f}ms vs {br.latency_ms:.1f}ms). "
                    f"Possible bottleneck: GPU compute type mismatch or cold model load."
                )

        lines.append("")

    # Benchmarks only in one profile
    only_baseline = sorted(set(b_bench.keys()) - set(t_bench.keys()))
    only_target = sorted(set(t_bench.keys()) - set(b_bench.keys()))

    if only_baseline:
        lines.append("## Benchmarks Only in Baseline\n")
        for key in only_baseline:
            r = b_bench[key]
            lines.append(f"- `{r.task_type}/{r.model}`: {r.latency_ms:.1f}ms, {r.throughput:.1f}/s")
        lines.append("")

    if only_target:
        lines.append("## Benchmarks Only in Target\n")
        for key in only_target:
            r = t_bench[key]
            lines.append(f"- `{r.task_type}/{r.model}`: {r.latency_ms:.1f}ms, {r.throughput:.1f}/s")
        lines.append("")

    if anomalies:
        lines.append("## Anomalies\n")
        for a in anomalies:
            lines.append(f"- {a}")
        lines.append("")

    if not common_keys and not only_baseline and not only_target:
        lines.append("_No benchmarks recorded in either profile._\n")

    return "\n".join(lines)
