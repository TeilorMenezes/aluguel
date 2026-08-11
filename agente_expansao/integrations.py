"""Fachada sobre os motores existentes no projeto público."""
from __future__ import annotations

import sys
import sqlite3
from contextlib import closing
from pathlib import Path

import yaml

from .config import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from descobrir_sites import (  # noqa: E402
    descobrir_urls_estado,
    descobrir_urls_regiao,
    dominio,
    listar_estados_ibge,
    listar_municipios_estado_ibge,
    listar_municipios_regiao_ibge,
    listar_regioes_imediatas_ibge,
    normalizar_texto,
)
from detector import avaliar_extracao, inspecionar_url  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


class ProjectAdapter:
    def __init__(self):
        self.last_skipped: list[dict] = []

    def known_agencies(self) -> dict:
        config = yaml.safe_load(
            (PROJECT_ROOT / "sites_config.yaml").read_text(encoding="utf-8")
        ) or {}
        domains, names, site_keys = set(), set(), set()
        for site_key, site in (config.get("sites") or {}).items():
            site_keys.add(site_key)
            host = dominio(site.get("base_url") or site.get("listagem_url") or "")
            if host:
                domains.add(host)
            if site.get("nome"):
                names.add(normalizar_texto(site["nome"]))

        for override_path in (
            PROJECT_ROOT / "public_data" / "selectors_override.yaml",
            PROJECT_ROOT / "agente_expansao" / "data" / "selectors_override.yaml",
        ):
            if not override_path.is_file():
                continue
            overrides = yaml.safe_load(override_path.read_text(encoding="utf-8")) or {}
            for site_key, site in (overrides.get("sites") or {}).items():
                site_keys.add(site_key)
                host = dominio(site.get("base_url") or site.get("listagem_url") or "")
                if host:
                    domains.add(host)
                if site.get("nome"):
                    names.add(normalizar_texto(site["nome"]))

        database_paths = (
            PROJECT_ROOT / "data" / "imoveis.db",
            PROJECT_ROOT / "public_data" / "imoveis.db",
        )
        for path in database_paths:
            if not path.is_file():
                continue
            try:
                with closing(sqlite3.connect(path)) as conn:
                    rows = conn.execute(
                        "SELECT DISTINCT site_key, imobiliaria, url FROM imoveis"
                    ).fetchall()
                for site_key, name, url in rows:
                    if site_key:
                        site_keys.add(site_key)
                    if name:
                        names.add(normalizar_texto(name))
                    host = dominio(url or "")
                    if host:
                        domains.add(host)
            except sqlite3.DatabaseError:
                continue
        return {"domains": domains, "names": names, "site_keys": site_keys}

    def states(self):
        return listar_estados_ibge()

    def regions(self, state: str):
        return listar_regioes_imediatas_ibge(state)

    def cities_in_region(self, region_id: int):
        return listar_municipios_regiao_ibge(region_id)

    def cities_in_state(self, state: str):
        return listar_municipios_estado_ibge(state)

    def discover(
        self, *, state: str, state_name: str, cities: list[str],
        region: str = "", limit: int = 8
    ) -> list[dict]:
        raw = (
            descobrir_urls_regiao(cities, limite=limit, uf=state)
            if cities
            else descobrir_urls_estado(state, state_name, limite=limit)
        )
        candidates = [
            {
                "domain": item.get("dominio") or dominio(item.get("base_url") or item["url"]),
                "name": item.get("nome_detectado") or item.get("titulo_busca", ""),
                "state": state,
                "region": region,
                "city": item.get("municipio", ""),
                "official_url": item.get("base_url") or item["url"],
                "rental_url": item.get("url_listagem") or item.get("url", ""),
                "discovery_score": float(item.get("score", 0)) / 100,
            }
            for item in raw
        ]
        known = self.known_agencies()
        accepted, skipped = [], []
        for item in candidates:
            same_domain = item["domain"] in known["domains"]
            same_name = bool(
                item.get("name")
                and normalizar_texto(item["name"]) in known["names"]
            )
            if same_domain or same_name:
                skipped.append(item)
            else:
                accepted.append(item)
        self.last_skipped = skipped
        return accepted

    def inspect(self, url: str) -> dict:
        result = inspecionar_url(url)
        if "erro" in result:
            result["error"] = result.pop("erro")
        return result

    def validate_learned_selectors(self, url: str, selectors: dict) -> dict:
        """Revalida no DOM renderizado uma correção aprendida anteriormente."""
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent="Mozilla/5.0 (compatible; AgenteExpansao/0.1)"
            )
            try:
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
                page.wait_for_timeout(4000)
                result = avaliar_extracao(page.content(), selectors, page.url)
                result.update({
                    "url": page.url,
                    "selectors": selectors,
                    "learned_pattern": True,
                })
                return result
            finally:
                browser.close()
