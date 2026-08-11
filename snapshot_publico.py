"""Contrato e utilitários do snapshot de imóveis consumido pelo site público."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public_data"
PUBLIC_DB_PATH = PUBLIC_DIR / "imoveis.db"
PUBLIC_MANIFEST_PATH = PUBLIC_DIR / "manifest.json"
SCHEMA_VERSION = 1
_INSTALL_LOCK = threading.Lock()

PUBLIC_COLUMNS = (
    "site_key", "imobiliaria", "logo_url", "url", "titulo", "tipo", "preco",
    "bairro", "cidade", "thumbnail_url", "latitude", "longitude", "coletado_em",
)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def _connect(path: str | Path):
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def _has_public_table(path: str | Path) -> bool:
    path = Path(path)
    if not path.is_file():
        return False
    try:
        with _connect(path) as conn:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(imoveis)").fetchall()
            }
        return set(PUBLIC_COLUMNS).issubset(columns)
    except sqlite3.DatabaseError:
        return False


def validate_snapshot(
    database_path: str | Path,
    manifest_path: str | Path | None = None,
) -> dict:
    database_path = Path(database_path)
    errors = []
    if not _has_public_table(database_path):
        return {"valid": False, "errors": ["Banco ausente ou esquema incompatível."]}

    with _connect(database_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM imoveis").fetchone()[0]
        invalid_required = conn.execute(
            """SELECT COUNT(*) FROM imoveis
               WHERE trim(COALESCE(site_key, '')) = ''
                  OR trim(COALESCE(imobiliaria, '')) = ''
                  OR trim(COALESCE(url, '')) = ''"""
        ).fetchone()[0]
        duplicate_urls = conn.execute(
            """SELECT COUNT(*) FROM (
                   SELECT url FROM imoveis GROUP BY url HAVING COUNT(*) > 1
               )"""
        ).fetchone()[0]
        metrics = conn.execute(
            """SELECT
                 AVG(CASE WHEN trim(COALESCE(titulo, '')) <> '' THEN 1.0 ELSE 0 END),
                 AVG(CASE WHEN preco IS NOT NULL AND preco >= 0 THEN 1.0 ELSE 0 END),
                 AVG(CASE WHEN trim(COALESCE(thumbnail_url, '')) <> '' THEN 1.0 ELSE 0 END)
               FROM imoveis"""
        ).fetchone()
        agencies = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT site_key, COUNT(*) FROM imoveis GROUP BY site_key ORDER BY site_key"
            ).fetchall()
        }

    quality = {
        "titulo": round(float(metrics[0] or 0), 3),
        "preco": round(float(metrics[1] or 0), 3),
        "imagem": round(float(metrics[2] or 0), 3),
        "link": 1.0 if total and not invalid_required else 0.0,
    }
    if total <= 0:
        errors.append("O snapshot não possui imóveis.")
    if invalid_required:
        errors.append(f"Há {invalid_required} registro(s) sem fonte, imobiliária ou link.")
    if duplicate_urls:
        errors.append(f"Há {duplicate_urls} link(s) duplicado(s).")
    if quality["titulo"] < 0.5:
        errors.append("Menos da metade dos imóveis possui título.")
    if quality["preco"] < 0.5:
        errors.append("Menos da metade dos imóveis possui preço reconhecido.")
    if quality["imagem"] < 0.35:
        errors.append("Poucos imóveis possuem imagem.")

    if manifest_path:
        manifest_path = Path(manifest_path)
        if not manifest_path.is_file():
            errors.append("Manifesto do snapshot ausente.")
        else:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("schema_version") != SCHEMA_VERSION:
                errors.append("Versão do esquema incompatível.")
            if manifest.get("sha256") != sha256_file(database_path):
                errors.append("Checksum do banco não corresponde ao manifesto.")

    return {
        "valid": not errors,
        "errors": errors,
        "total": total,
        "agencies": agencies,
        "quality": quality,
        "sha256": sha256_file(database_path),
    }


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE imoveis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_key TEXT NOT NULL,
            imobiliaria TEXT NOT NULL,
            logo_url TEXT,
            url TEXT NOT NULL UNIQUE,
            titulo TEXT,
            tipo TEXT,
            preco REAL,
            bairro TEXT,
            cidade TEXT,
            thumbnail_url TEXT,
            latitude REAL,
            longitude REAL,
            coletado_em TEXT
        );
        CREATE INDEX idx_imoveis_site ON imoveis(site_key);
        CREATE INDEX idx_imoveis_cidade ON imoveis(cidade);
        CREATE TABLE snapshot_meta (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
        """
    )


def _read_rows(path: Path, site_keys: set[str] | None = None) -> list[tuple]:
    if not _has_public_table(path):
        raise ValueError(f"Banco de origem inválido: {path}")
    columns = ", ".join(PUBLIC_COLUMNS)
    query = f"SELECT {columns} FROM imoveis"
    params: list[str] = []
    if site_keys is not None:
        if not site_keys:
            return []
        query += f" WHERE site_key IN ({','.join('?' for _ in site_keys)})"
        params.extend(sorted(site_keys))
    with _connect(path) as conn:
        return [tuple(row) for row in conn.execute(query, params).fetchall()]


def create_snapshot(
    source_db: str | Path,
    output_db: str | Path,
    output_manifest: str | Path,
    *,
    mode: str = "complete",
    selected_site_keys: set[str] | None = None,
    base_snapshot: str | Path | None = None,
) -> dict:
    """Cria substituição completa ou mescla parcial de forma atômica."""
    source_db = Path(source_db)
    output_db = Path(output_db)
    output_manifest = Path(output_manifest)
    selected = set(selected_site_keys or [])
    if mode not in {"complete", "partial"}:
        raise ValueError("Modo deve ser 'complete' ou 'partial'.")
    if mode == "partial" and not selected:
        raise ValueError("Selecione ao menos uma imobiliária para atualização parcial.")
    if mode == "partial" and not base_snapshot:
        raise ValueError("A atualização parcial exige um snapshot público anterior.")

    rows_by_url: dict[str, tuple] = {}
    if mode == "partial":
        for row in _read_rows(Path(base_snapshot)):
            if row[0] not in selected:
                rows_by_url[row[3]] = row
        source_rows = _read_rows(source_db, selected)
    else:
        source_rows = _read_rows(source_db)
    for row in source_rows:
        rows_by_url[row[3]] = row
    if mode == "partial" and not source_rows:
        raise ValueError("A coleta local não possui imóveis das fontes selecionadas.")

    output_db.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_db.with_suffix(output_db.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    with _connect(temporary) as conn:
        _create_schema(conn)
        placeholders = ",".join("?" for _ in PUBLIC_COLUMNS)
        conn.executemany(
            f"INSERT INTO imoveis ({', '.join(PUBLIC_COLUMNS)}) VALUES ({placeholders})",
            rows_by_url.values(),
        )
        conn.executemany(
            "INSERT INTO snapshot_meta(chave, valor) VALUES (?, ?)",
            (
                ("schema_version", str(SCHEMA_VERSION)),
                ("created_at", datetime.now().astimezone().isoformat(timespec="seconds")),
                ("mode", mode),
            ),
        )
    temporary.replace(output_db)

    validation = validate_snapshot(output_db)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": mode,
        "selected_site_keys": sorted(selected),
        "total": validation["total"],
        "agencies": validation["agencies"],
        "quality": validation["quality"],
        "sha256": validation["sha256"],
    }
    output_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return validate_snapshot(output_db, output_manifest)


def install_public_snapshot_if_needed(target_db: str | Path) -> bool:
    """Instala atomicamente o snapshot quando sua versão publicada mudar.

    O arquivo de marcação identifica qual checksum já foi aplicado. Isso evita
    substituir o banco em cada rerun do Streamlit, mas permite que um snapshot
    novo substitua um banco efêmero antigo que tenha sobrevivido ao deploy.
    """
    target_db = Path(target_db)
    if not PUBLIC_DB_PATH.is_file():
        return False
    validation = validate_snapshot(PUBLIC_DB_PATH, PUBLIC_MANIFEST_PATH)
    if not validation["valid"]:
        return False
    checksum = validation["sha256"]
    marker = target_db.with_suffix(target_db.suffix + ".snapshot.sha256")

    with _INSTALL_LOCK:
        applied = marker.read_text(encoding="ascii").strip() if marker.is_file() else ""
        if target_db.is_file() and _has_public_table(target_db) and applied == checksum:
            return False

        target_db.parent.mkdir(parents=True, exist_ok=True)
        temporary_db = target_db.with_suffix(target_db.suffix + ".snapshot.tmp")
        temporary_marker = marker.with_suffix(marker.suffix + ".tmp")
        try:
            if temporary_db.exists():
                temporary_db.unlink()
            shutil.copy2(PUBLIC_DB_PATH, temporary_db)
            copied = validate_snapshot(temporary_db, PUBLIC_MANIFEST_PATH)
            if not copied["valid"]:
                return False
            try:
                temporary_db.replace(target_db)
            except PermissionError:
                # No Windows, uma sessão de leitura pode manter o arquivo aberto.
                # O backup nativo do SQLite substitui o conteúdo dentro de uma
                # transação consistente sem exigir a troca do arquivo aberto.
                with _connect(temporary_db) as source, _connect(target_db) as target:
                    source.backup(target)
            temporary_marker.write_text(checksum + "\n", encoding="ascii")
            temporary_marker.replace(marker)
            return True
        finally:
            if temporary_db.exists():
                temporary_db.unlink()
            if temporary_marker.exists():
                temporary_marker.unlink()
