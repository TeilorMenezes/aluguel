"""Avalia o detector em fontes cadastradas sem coletar ou persistir anúncios."""
from __future__ import annotations

import argparse
import json
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from detector import inspecionar_url
from url_safety import verificar_robots

from .collection import configured_sites


USER_AGENT = "MapaDoAluguelDetector/1.0 (+painel-local; contato-administrador)"


def _robots_allows(url: str) -> tuple[bool, str]:
    try:
        return True, verificar_robots(url)
    except Exception as exc:
        return False, f"robots_bloqueado:{exc}"


def evaluate_registered_sites(
    site_keys: list[str] | None = None, *, limit: int = 3, delay_seconds: float = 3.0
) -> list[dict]:
    sites = configured_sites()
    selected = site_keys or list(sites)[:limit]
    results = []
    for index, site_key in enumerate(selected[:limit]):
        site = sites.get(site_key)
        if not site:
            results.append({"site_key": site_key, "status": "nao_cadastrado"})
            continue
        url = site.get("listagem_url") or site.get("base_url")
        if not url or "{pagina}" in url:
            url = (url or "").replace("{pagina}", "1")
        allowed, policy = _robots_allows(url)
        if not allowed:
            results.append({"site_key": site_key, "status": "bloqueado", "policy": policy})
            continue
        if index:
            time.sleep(max(0.0, delay_seconds))
        inspection = inspecionar_url(url, verify_policy=False)
        results.append({
            "site_key": site_key,
            "status": "ok" if not inspection.get("erro") else "erro",
            "policy": policy,
            "publicavel": bool(inspection.get("publicavel")),
            "confianca": inspection.get("confianca", 0),
            "qualidade_extracao": inspection.get("qualidade_extracao", 0),
            "cards": inspection.get("cards_encontrados", 0),
            "taxas_campos": inspection.get("taxas_campos", {}),
            "seletores": inspection.get("seletores", {}),
            "erro": inspection.get("erro"),
            "ia": inspection.get("ia", {"used": False}),
        })
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("site_keys", nargs="*")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--delay", type=float, default=3.0)
    args = parser.parse_args()
    print(json.dumps(
        evaluate_registered_sites(args.site_keys or None, limit=max(1, min(args.limit, 10)), delay_seconds=args.delay),
        ensure_ascii=False, indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
