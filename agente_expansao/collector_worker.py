"""Processo isolado usado pela coleta local para não tocar o banco público."""
from __future__ import annotations

import argparse
import json
import os


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--overrides", required=True)
    parser.add_argument("--sites", nargs="*")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--history")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    os.environ["IMOVEIS_DB_PATH"] = args.db
    os.environ["IMOVEIS_SELECTORS_OVERRIDE"] = args.overrides
    os.environ["IMOVEIS_AUTO_PAGINATION"] = "1"
    if args.history:
        os.environ["IMOVEIS_STRATEGY_HISTORY"] = args.history

    import db
    from agente_expansao.resources import recommended_workers
    from scraper import carregar_config, rodar_varredura

    db.init_db()

    config = carregar_config().get("sites", {})
    selected = [key for key in config if not args.sites or key in args.sites]
    resumed_sites = []
    if args.resume:
        completed = {
            item["site_key"] for item in db.listar_status_sites()
            if item.get("status") == "concluido"
        }
        resumed_sites = [key for key in selected if key in completed]
        selected = [key for key in selected if key not in completed]
    api_sites = [key for key in selected if "api" in str(config[key].get("integracao", "")).lower()]
    browser_sites = [key for key in selected if key not in api_sites]
    total, errors, capacity_history = 0, [], []
    manual_maximum = args.workers if args.workers > 0 else None

    if api_sites:
        capacity = recommended_workers("api", manual_maximum)
        capacity_history.append(capacity)
        collected, error = rodar_varredura(
            sites_filtrados=api_sites,
            headless=True,
            max_workers=min(capacity["workers"], len(api_sites)),
            max_tentativas=max(1, min(args.attempts, 5)),
        )
        total += collected
        if error:
            errors.append(error)

    remaining = list(browser_sites)
    while remaining:
        capacity = recommended_workers("browser", manual_maximum)
        batch_size = min(capacity["workers"], len(remaining))
        batch, remaining = remaining[:batch_size], remaining[batch_size:]
        capacity_history.append({**capacity, "sites": batch})
        collected, error = rodar_varredura(
            sites_filtrados=batch,
            headless=True,
            max_workers=batch_size,
            max_tentativas=max(1, min(args.attempts, 5)),
        )
        total += collected
        if error:
            errors.append(error)

    print(json.dumps({
        "total": total,
        "error": " | ".join(errors) if errors else None,
        "capacity_history": capacity_history,
        "sites_retomados": resumed_sites,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
