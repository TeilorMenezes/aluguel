"""
Camada de acesso ao banco de dados SQLite.
Armazena os imóveis coletados e um cache de geocodificação (bairro -> lat/lon)
para evitar bater no serviço de geocoding repetidamente.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "imoveis.db"
DB_PATH.parent.mkdir(exist_ok=True)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS imoveis (
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
            )
        """)


def remover_duplicata_diferencial():
    """Remove a antiga integração HTML da Diferencial, substituída pela API."""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM imoveis WHERE site_key = ? OR imobiliaria = ?",
            ("diferencialimoveis", "diferencialimoveis.com"),
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS geocode_cache (
                chave TEXT PRIMARY KEY,
                latitude REAL,
                longitude REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS execucoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                executado_em TEXT,
                tipo TEXT,
                imoveis_coletados INTEGER,
                erro TEXT
            )
        """)


def upsert_imovel(item: dict):
    """Insere ou atualiza um imóvel (chave única = url)."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO imoveis
                (site_key, imobiliaria, logo_url, url, titulo, tipo, preco,
                 bairro, cidade, thumbnail_url, latitude, longitude, coletado_em)
            VALUES (:site_key, :imobiliaria, :logo_url, :url, :titulo, :tipo, :preco,
                    :bairro, :cidade, :thumbnail_url, :latitude, :longitude, :coletado_em)
            ON CONFLICT(url) DO UPDATE SET
                preco=excluded.preco,
                bairro=excluded.bairro,
                cidade=excluded.cidade,
                thumbnail_url=excluded.thumbnail_url,
                titulo=excluded.titulo,
                tipo=excluded.tipo,
                latitude=COALESCE(excluded.latitude, imoveis.latitude),
                longitude=COALESCE(excluded.longitude, imoveis.longitude),
                coletado_em=excluded.coletado_em
        """, item)


def remover_ausentes(site_key: str, urls_ativas: list):
    """Remove do banco imóveis que não apareceram mais na última varredura
    (ou seja, provavelmente já foram alugados/removidos do site)."""
    if not urls_ativas:
        return
    with get_conn() as conn:
        placeholders = ",".join("?" * len(urls_ativas))
        conn.execute(
            f"DELETE FROM imoveis WHERE site_key = ? AND url NOT IN ({placeholders})",
            [site_key, *urls_ativas],
        )


def listar_imoveis(preco_min=None, preco_max=None, bairros=None, cidades=None, tipos=None, imobiliarias=None, ordenar_por="recentes"):
    query = "SELECT * FROM imoveis WHERE 1=1"
    params = []
    if preco_min is not None:
        query += " AND preco >= ?"
        params.append(preco_min)
    if preco_max is not None:
        query += " AND preco <= ?"
        params.append(preco_max)
    if bairros:
        placeholders = ",".join("?" * len(bairros))
        query += f" AND bairro IN ({placeholders})"
        params.extend(bairros)
    if cidades:
        placeholders = ",".join("?" * len(cidades))
        query += f" AND cidade IN ({placeholders})"
        params.extend(cidades)
    if tipos:
        placeholders = ",".join("?" * len(tipos))
        query += f" AND tipo IN ({placeholders})"
        params.extend(tipos)
    if imobiliarias:
        placeholders = ",".join("?" * len(imobiliarias))
        query += f" AND imobiliaria IN ({placeholders})"
        params.extend(imobiliarias)

    ordens = {
        "recentes": "coletado_em DESC",
        "preco_asc": "preco ASC",
        "preco_desc": "preco DESC",
    }
    query += f" ORDER BY {ordens.get(ordenar_por, ordens['recentes'])}"

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def listar_cidades():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT cidade FROM imoveis WHERE cidade IS NOT NULL ORDER BY cidade"
        ).fetchall()
        return [r["cidade"] for r in rows]


def listar_tipos(cidades=None, bairros=None):
    query = "SELECT DISTINCT tipo FROM imoveis WHERE tipo IS NOT NULL"
    params = []
    if cidades:
        placeholders = ",".join("?" * len(cidades))
        query += f" AND cidade IN ({placeholders})"
        params.extend(cidades)
    if bairros:
        placeholders = ",".join("?" * len(bairros))
        query += f" AND bairro IN ({placeholders})"
        params.extend(bairros)
    query += " ORDER BY tipo"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [r["tipo"] for r in rows]


def listar_imobiliarias(cidades=None, bairros=None):
    query = "SELECT DISTINCT imobiliaria FROM imoveis WHERE imobiliaria IS NOT NULL"
    params = []
    if cidades:
        placeholders = ",".join("?" * len(cidades))
        query += f" AND cidade IN ({placeholders})"
        params.extend(cidades)
    if bairros:
        placeholders = ",".join("?" * len(bairros))
        query += f" AND bairro IN ({placeholders})"
        params.extend(bairros)
    query += " ORDER BY imobiliaria"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [r["imobiliaria"] for r in rows]


def listar_bairros(cidades=None):
    query = "SELECT DISTINCT bairro FROM imoveis WHERE bairro IS NOT NULL"
    params = []
    if cidades:
        placeholders = ",".join("?" * len(cidades))
        query += f" AND cidade IN ({placeholders})"
        params.extend(cidades)
    query += " ORDER BY bairro"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [r["bairro"] for r in rows]


def faixa_preco():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MIN(preco) as min_p, MAX(preco) as max_p FROM imoveis WHERE preco IS NOT NULL"
        ).fetchone()
        return (row["min_p"] or 0, row["max_p"] or 0)


def get_geocode_cache(chave: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT latitude, longitude FROM geocode_cache WHERE chave = ?", (chave,)
        ).fetchone()
        return (row["latitude"], row["longitude"]) if row else None


def set_geocode_cache(chave: str, lat, lon):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO geocode_cache (chave, latitude, longitude) VALUES (?, ?, ?)",
            (chave, lat, lon),
        )


def registrar_execucao(tipo: str, imoveis_coletados: int, erro: str = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO execucoes (executado_em, tipo, imoveis_coletados, erro) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), tipo, imoveis_coletados, erro),
        )


def ultima_execucao():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM execucoes ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
