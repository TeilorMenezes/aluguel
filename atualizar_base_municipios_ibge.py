"""Atualiza a referência pública de municípios a partir da API do IBGE."""
from __future__ import annotations

import json
import gzip
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen


URL_MUNICIPIOS = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
DESTINO = Path(__file__).resolve().parent / "public_data" / "municipios_ibge.json"


def main():
    requisicao = Request(URL_MUNICIPIOS, headers={"User-Agent": "MapaDoAluguel/1.0"})
    with urlopen(requisicao, timeout=30) as resposta:
        corpo = resposta.read()
    if corpo.startswith(b"\x1f\x8b"):
        corpo = gzip.decompress(corpo)
    dados = json.loads(corpo.decode("utf-8"))
    municipios = sorted(
        ({"id": int(item["id"]), "nome": item["nome"]} for item in dados),
        key=lambda item: item["nome"],
    )
    if len(municipios) < 5_000:
        raise RuntimeError("Resposta do IBGE incompleta; referência não foi atualizada.")
    conteudo = {
        "fonte": "IBGE — API de Localidades / municípios",
        "atualizado_em": datetime.now(UTC).isoformat(timespec="seconds"),
        "municipios": municipios,
    }
    temporario = DESTINO.with_suffix(".tmp")
    temporario.write_text(json.dumps(conteudo, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporario.replace(DESTINO)
    print(f"{len(municipios)} municípios atualizados em {DESTINO}")


if __name__ == "__main__":
    main()
