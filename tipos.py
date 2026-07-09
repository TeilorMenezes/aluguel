"""
Normaliza o texto bruto de "tipo de imóvel" extraído dos sites (que varia
muito de site para site, ex: "Apto", "STUDIO", "Kit-net", "Casa em
condomínio"...) em categorias padronizadas para exibir no filtro.
"""
import re
import unicodedata


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# Cada categoria final tem uma lista de padrões (regex, já sem acento e em
# minúsculo) que identificam essa categoria no texto bruto do site.
_REGRAS = [
    ("Apartamento", re.compile(
        r"apart|\bapto\b|\bap\b|kit\s*-?\s*net|kitinet|quitinet|\bkit\b|"
        r"studio|est[uú]dio|\bflat\b|cobertura|duplex|triplex"
    )),
    ("Casa", re.compile(r"\bcasa\b|sobrado|chac|s[ií]tio")),
    ("Galpão", re.compile(r"galp[aã]o|barrac[aã]o|pavilh[aã]o")),
    ("Loja", re.compile(r"\bloja\b|ponto\s+comercial")),
    ("Sala Comercial", re.compile(r"\bsala\b")),
    ("Terreno/Lote", re.compile(r"\bterreno\b|\blote\b")),
    ("Prédio Comercial", re.compile(r"pr[eé]dio")),
]


def normalizar_tipo(tipo_bruto: str):
    """Recebe o texto de tipo extraído do site (ex: 'Kit-net', 'STUDIO',
    'Casa em condomínio') e retorna uma categoria padronizada
    (ex: 'Apartamento'). Retorna None se o texto for vazio/desconhecido
    demais para classificar (nesse caso, mantém o texto original
    capitalizado como categoria própria)."""
    if not tipo_bruto or not tipo_bruto.strip():
        return None

    texto = _sem_acento(tipo_bruto.strip().lower())

    for categoria, padrao in _REGRAS:
        if padrao.search(texto):
            return categoria

    # Não bateu com nenhuma regra conhecida: usa o texto original
    # capitalizado como categoria própria, em vez de descartar a
    # informação (assim novos tipos ainda aparecem no filtro).
    return tipo_bruto.strip().title()
