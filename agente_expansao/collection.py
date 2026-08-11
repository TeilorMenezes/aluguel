"""Coleta local isolada, prévia e preparação dos snapshots públicos."""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml
import requests

from snapshot_publico import (
    PUBLIC_DB_PATH,
    PUBLIC_MANIFEST_PATH,
    create_snapshot,
    validate_snapshot,
)

from .config import (
    LOCAL_COLLECTION_DB,
    LOCAL_OVERRIDE_PATH,
    PROJECT_ROOT,
    PUBLIC_BASE_CACHE_DIR,
    PROPOSAL_DB_PATH,
    PROPOSAL_MANIFEST_PATH,
    PROPOSAL_OVERRIDE_PATH,
    STRATEGY_HISTORY_PATH,
)


def _public_base_snapshot() -> Path:
    local_validation = validate_snapshot(PUBLIC_DB_PATH, PUBLIC_MANIFEST_PATH)
    if local_validation.get("valid"):
        return PUBLIC_DB_PATH

    database = PUBLIC_BASE_CACHE_DIR / "imoveis.db"
    manifest = PUBLIC_BASE_CACHE_DIR / "manifest.json"
    cached_validation = validate_snapshot(database, manifest)
    if cached_validation.get("valid"):
        return database

    PUBLIC_BASE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    base_url = "https://raw.githubusercontent.com/TeilorMenezes/aluguel/main/public_data"
    for name, target in (("imoveis.db", database), ("manifest.json", manifest)):
        response = requests.get(f"{base_url}/{name}", timeout=60)
        if response.status_code == 404:
            raise ValueError(
                "Ainda não existe snapshot no site público. Faça primeiro uma substituição completa."
            )
        response.raise_for_status()
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(response.content)
        temporary.replace(target)
    remote_validation = validate_snapshot(database, manifest)
    if not remote_validation.get("valid"):
        raise ValueError("O snapshot atual do GitHub não passou na validação de integridade.")
    return database


def configured_sites() -> dict:
    config = yaml.safe_load(
        (PROJECT_ROOT / "sites_config.yaml").read_text(encoding="utf-8")
    ) or {}
    sites = config.get("sites") or {}
    if LOCAL_OVERRIDE_PATH.is_file():
        overrides = yaml.safe_load(
            LOCAL_OVERRIDE_PATH.read_text(encoding="utf-8")
        ) or {}
        for key, learned in (overrides.get("sites") or {}).items():
            if key not in sites and {"nome", "base_url", "listagem_url", "seletores"}.issubset(learned):
                sites[key] = learned
    return sites


def _ensure_override_file() -> None:
    if not LOCAL_OVERRIDE_PATH.is_file():
        LOCAL_OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOCAL_OVERRIDE_PATH.write_text("sites: {}\n", encoding="utf-8")


def run_local_collection(
    site_keys: list[str] | None = None,
    *,
    fresh: bool = False,
    workers: int = 0,
    attempts: int = 3,
    timeout: int = 60 * 60,
) -> dict:
    """Executa o scraper em subprocesso e troca o staging só ao terminar."""
    _ensure_override_file()
    LOCAL_COLLECTION_DB.parent.mkdir(parents=True, exist_ok=True)
    working = LOCAL_COLLECTION_DB.with_suffix(".working.db")
    if fresh and working.exists():
        working.unlink()
    resuming = working.exists()
    if not resuming and LOCAL_COLLECTION_DB.is_file() and not fresh:
        shutil.copy2(LOCAL_COLLECTION_DB, working)

    command = [
        sys.executable,
        "-m",
        "agente_expansao.collector_worker",
        "--db",
        str(working),
        "--overrides",
        str(LOCAL_OVERRIDE_PATH),
        "--workers",
        str(workers),
        "--attempts",
        str(attempts),
        "--history",
        str(STRATEGY_HISTORY_PATH),
    ]
    if resuming:
        command.append("--resume")
    if site_keys:
        command.extend(["--sites", *site_keys])
    try:
        process = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "A coleta excedeu o tempo disponível. O progresso foi preservado; "
            "execute novamente para retomar das imobiliárias pendentes."
        ) from exc
    if process.returncode or not working.is_file():
        raise RuntimeError(
            (process.stderr or process.stdout or "A coleta local falhou.").strip()
        )
    output = {}
    for line in reversed(process.stdout.splitlines()):
        try:
            output = json.loads(line)
            break
        except json.JSONDecodeError:
            continue

    backup = None
    if LOCAL_COLLECTION_DB.is_file():
        backup = LOCAL_COLLECTION_DB.with_name(
            f"coleta_local.backup-{datetime.now():%Y%m%d-%H%M%S}.db"
        )
        shutil.copy2(LOCAL_COLLECTION_DB, backup)
    working.replace(LOCAL_COLLECTION_DB)
    preview = collection_preview()
    return {
        **output,
        **preview,
        "backup": str(backup) if backup else "",
        "resumed": resuming,
        "stdout": process.stdout,
    }


def collection_checkpoint_available() -> bool:
    return LOCAL_COLLECTION_DB.with_suffix(".working.db").is_file()


def strategy_history(limit: int = 250) -> list[dict]:
    if not STRATEGY_HISTORY_PATH.is_file():
        return []
    records = []
    for line in STRATEGY_HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(records[-limit:]))


def collection_preview(limit: int = 100) -> dict:
    if not LOCAL_COLLECTION_DB.is_file():
        return {"available": False, "total": 0, "agencies": {}, "rows": [], "statuses": []}
    validation = validate_snapshot(LOCAL_COLLECTION_DB)
    if "total" not in validation:
        return {"available": False, **validation, "rows": [], "statuses": []}
    with closing(sqlite3.connect(LOCAL_COLLECTION_DB)) as conn:
        conn.row_factory = sqlite3.Row
        rows = [
            dict(row) for row in conn.execute(
                """SELECT site_key, imobiliaria, titulo, preco, bairro, cidade,
                          thumbnail_url, url, coletado_em
                   FROM imoveis ORDER BY coletado_em DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        ]
        statuses = [
            dict(row) for row in conn.execute(
                "SELECT * FROM coletas_site ORDER BY site_key"
            ).fetchall()
        ]
    return {"available": True, **validation, "rows": rows, "statuses": statuses}


def prepare_snapshot(mode: str, selected_site_keys: set[str] | None = None) -> dict:
    if not LOCAL_COLLECTION_DB.is_file():
        raise ValueError("Execute uma raspagem local antes de preparar o snapshot.")
    PROPOSAL_DIR = PROPOSAL_DB_PATH.parent
    PROPOSAL_DIR.mkdir(parents=True, exist_ok=True)
    validation = create_snapshot(
        LOCAL_COLLECTION_DB,
        PROPOSAL_DB_PATH,
        PROPOSAL_MANIFEST_PATH,
        mode=mode,
        selected_site_keys=selected_site_keys,
        base_snapshot=_public_base_snapshot() if mode == "partial" else None,
    )
    _ensure_override_file()
    shutil.copy2(LOCAL_OVERRIDE_PATH, PROPOSAL_OVERRIDE_PATH)
    return validation


def proposal_preview(limit: int = 100) -> dict:
    validation = validate_snapshot(PROPOSAL_DB_PATH, PROPOSAL_MANIFEST_PATH)
    if "total" not in validation:
        return {**validation, "rows": []}
    with closing(sqlite3.connect(PROPOSAL_DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = [
            dict(row) for row in conn.execute(
                """SELECT site_key, imobiliaria, titulo, preco, bairro, cidade,
                          thumbnail_url, url
                   FROM imoveis ORDER BY site_key, titulo LIMIT ?""",
                (limit,),
            ).fetchall()
        ]
    return {**validation, "rows": rows}


def candidate_site_key(candidate: dict) -> str:
    host = urlparse(candidate.get("official_url") or candidate.get("domain") or "").hostname
    base = (host or candidate.get("domain") or "imobiliaria").removeprefix("www.").split(".")[0]
    return re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")


def save_selector_override(
    site_key: str,
    list_url: str,
    selectors: dict,
    site_config: dict | None = None,
    pagination: dict | None = None,
    filters: dict | None = None,
) -> None:
    if not {"card", "link", "titulo", "preco", "thumbnail"}.issubset(selectors):
        raise ValueError("Selecione card, link, título, preço e imagem.")
    if site_key not in configured_sites() and not site_config:
        raise ValueError("A imobiliária não existe em sites_config.yaml.")
    _ensure_override_file()
    current = yaml.safe_load(LOCAL_OVERRIDE_PATH.read_text(encoding="utf-8")) or {}
    previous = current.setdefault("sites", {}).get(site_key, {})
    learned = {
        **previous,
        **(site_config or {}),
        "listagem_url": list_url,
        "espera_seletor": selectors["card"],
        "seletores": selectors,
        "aprendido_em": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    if pagination:
        learned["paginacao"] = pagination
    if filters:
        learned["filtros"] = filters
    current["sites"][site_key] = learned
    LOCAL_OVERRIDE_PATH.write_text(
        yaml.safe_dump(current, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
