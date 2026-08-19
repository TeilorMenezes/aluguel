"""Referência pública de municípios do IBGE usada pelos filtros."""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path


ARQUIVO_MUNICIPIOS = Path(__file__).resolve().parent / "public_data" / "municipios_ibge.json"


def _chave(valor: str) -> str:
    texto = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", valor)
        if not unicodedata.combining(caractere)
    ).lower()
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


@lru_cache(maxsize=1)
def municipios_ibge() -> dict[str, str]:
    """Retorna nome oficial por chave tolerante a acentos e pontuação.

    A aplicação não consulta a rede em cada filtro: usa o arquivo público
    gerado pelo atualizador administrativo.
    """
    try:
        conteudo = json.loads(ARQUIVO_MUNICIPIOS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        _chave(registro["nome"]): registro["nome"]
        for registro in conteudo.get("municipios", [])
        if isinstance(registro, dict) and isinstance(registro.get("nome"), str)
    }


def nome_municipio_ibge(valor: str | None) -> str | None:
    if not valor:
        return None
    return municipios_ibge().get(_chave(valor))
