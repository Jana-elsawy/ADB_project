"""Shared measurement helpers for the M2 benchmarks."""
import contextlib
import math
import os
import platform
import shutil
import statistics
import sys
import tempfile
from pathlib import Path


@contextlib.contextmanager
def tmpdir():
    """Scratch directory in the system temp folder (not inside OneDrive)."""
    d = Path(tempfile.mkdtemp(prefix="aerocore_bench_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def mean_std(xs):
    return statistics.mean(xs), (statistics.stdev(xs) if len(xs) > 1 else 0.0)


def percentile(sorted_vals, q):
    return sorted_vals[max(0, math.ceil(q * len(sorted_vals)) - 1)]


def repeat(fn, runs, warmup=1):
    """Run fn warmup times (discarded) then `runs` measured times; fn returns a result dict."""
    for _ in range(warmup):
        fn()
    return [fn() for _ in range(runs)]


def summarize(results, ops):
    """Aggregate repeated runs. Each result: elapsed (s), optional lat (list of s), reads, writes, size, ok."""
    mean, std = mean_std([r["elapsed"] for r in results])
    row = {"runs": len(results), "ops_per_run": ops, "mean_s": round(mean, 6), "std_s": round(std, 6),
           "ops_per_sec": round(ops / mean, 1) if mean else 0}
    lat = sorted(x for r in results for x in r.get("lat", []))
    row["median_ms"] = round(statistics.median(lat) * 1000, 4) if lat else ""
    row["p95_ms"] = round(percentile(lat, 0.95) * 1000, 4) if lat else ""
    row["page_reads_per_op"] = round(statistics.mean(r.get("reads", 0) for r in results) / ops, 3)
    row["page_writes_per_op"] = round(statistics.mean(r.get("writes", 0) for r in results) / ops, 3)
    row["size_kb"] = round(statistics.mean(r.get("size", 0) for r in results) / 1024, 1)
    row["correct"] = all(r.get("ok", True) for r in results)
    return row


def _ram_gb():
    try:
        import psutil
        return round(psutil.virtual_memory().total / 2**30, 1)
    except Exception:
        pass
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("m", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong), ("c", ctypes.c_ulonglong),
                            ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong), ("f", ctypes.c_ulonglong)]
            m = MS()
            m.l = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return round(m.total / 2**30, 1)
        with open("/proc/meminfo") as f:
            return round(int(f.readline().split()[1]) / 2**20, 1)
    except Exception:
        return None


def environment(extra):
    env = {"os": platform.platform(), "python": sys.version.split()[0],
           "processor": platform.processor() or platform.machine(), "cpu_count": os.cpu_count(),
           "ram_gb": _ram_gb(), "concurrency": "single-threaded"}
    env.update(extra)
    return env