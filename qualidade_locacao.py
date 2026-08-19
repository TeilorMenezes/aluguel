"""Regras determinísticas para publicar somente ofertas de locação confiáveis."""
from __future__ import annotations

import re


_ALUGUEL_RE = re.compile(r"alugu|loca[cç]|\brent\b|por\s+m[eê]s|/\s*m[eê]s", re.I)
_VENDA_RE = re.compile(r"\bvenda\b|\bvende\b|\bcompr", re.I)
_MENSAL_RE = re.compile(r"alugu|loca[cç]|mensal|por\s+m[eê]s|/\s*m[eê]s", re.I)


def revisar_anuncio_locacao(titulo, url, preco, *, contexto_preco=None):
    """Decide se um anúncio pode entrar no catálogo de aluguel.

    A fonte pode oferecer venda e locação no mesmo card. Sem uma indicação
    inequívoca de valor mensal, é preferível publicar o link como ``sob
    consulta`` a mostrar o preço de venda como se fosse aluguel.
    """
    contexto = " ".join(str(valor or "") for valor in (titulo, url, contexto_preco))
    ha_aluguel = bool(_ALUGUEL_RE.search(contexto))
    ha_venda = bool(_VENDA_RE.search(contexto))

    if ha_venda and not ha_aluguel:
        return {"publicar": False, "preco": None, "motivo": "anúncio de venda"}

    try:
        valor = float(preco) if preco is not None else None
    except (TypeError, ValueError):
        valor = None
    if valor is None:
        return {"publicar": True, "preco": None, "motivo": None}

    # R$ 1,00 costuma ser a antiga leitura de "1,000" como decimal. Um
    # aluguel genuíno abaixo de R$ 10 também não deve ser exibido sem revisão.
    if 0 < valor < 10:
        return {"publicar": True, "preco": None, "motivo": "preço mensal implausível"}

    # Valores muito altos podem ser locações comerciais legítimas, mas somente
    # são mostrados quando o próprio campo de preço traz evidência mensal. Ao
    # revisar um snapshot antigo, esse campo não existe; nesses casos o valor
    # fica sob consulta até uma coleta atual confirmar a mensalidade.
    if valor >= 100_000 and not _MENSAL_RE.search(str(contexto_preco or "")):
        return {"publicar": True, "preco": None, "motivo": "valor alto sem período mensal"}

    # Em oferta mista, não aceite um número isolado como aluguel. O campo de
    # preço precisa identificar que aquele número pertence à locação.
    if ha_venda and ha_aluguel and not _MENSAL_RE.search(str(contexto_preco or "")):
        return {"publicar": True, "preco": None, "motivo": "oferta mista sem preço mensal"}

    return {"publicar": True, "preco": valor, "motivo": None}
