"""Dimensionamento agressivo, porém adaptativo, para o computador local."""
from __future__ import annotations

import os

try:
    import psutil
except ImportError:  # fallback conservador até o instalador atualizar dependências
    psutil = None


def capacity_snapshot() -> dict:
    logical = max(1, (psutil.cpu_count(logical=True) if psutil else os.cpu_count()) or 1)
    physical = max(1, psutil.cpu_count(logical=False) or logical // 2) if psutil else max(1, logical // 2)
    if psutil:
        memory = psutil.virtual_memory()
        available_gb = memory.available / 1024 ** 3
        total_gb = memory.total / 1024 ** 3
        memory_percent = memory.percent
        cpu_percent = psutil.cpu_percent(interval=0.25)
    else:
        available_gb, total_gb, memory_percent, cpu_percent = 4.0, 8.0, 50.0, 0.0
    return {
        "logical_cpus": logical,
        "physical_cpus": physical,
        "available_ram_gb": round(available_gb, 2),
        "total_ram_gb": round(total_gb, 2),
        "memory_percent": round(memory_percent, 1),
        "cpu_percent": round(cpu_percent, 1),
    }


def recommended_workers(kind: str = "browser", maximum: int | None = None) -> dict:
    state = capacity_snapshot()
    reserve_gb = 2.0
    if kind == "api":
        by_cpu = state["logical_cpus"] * 2
        by_memory = max(1, int((state["available_ram_gb"] - reserve_gb) / 0.18))
        hard_cap = 16
    else:
        by_cpu = state["logical_cpus"]
        by_memory = max(1, int((state["available_ram_gb"] - reserve_gb) / 0.70))
        hard_cap = 12
    workers = max(1, min(by_cpu, by_memory, hard_cap, maximum or hard_cap))
    if state["cpu_percent"] >= 95 or state["available_ram_gb"] < 2.0:
        workers = 1
    elif state["cpu_percent"] >= 88 or state["available_ram_gb"] < 3.0:
        workers = max(1, workers // 2)
    elif state["cpu_percent"] >= 80:
        workers = max(1, int(workers * 0.75))
    return {**state, "kind": kind, "workers": workers}
