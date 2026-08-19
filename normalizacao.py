"""Regras únicas para os campos usados nos filtros e no mapa."""
import re
import unicodedata


def _sem_acento(valor: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", valor) if not unicodedata.combining(c))


def limpar_texto(valor):
    if valor is None:
        return None
    texto = re.sub(r"\s+", " ", str(valor).replace("\xa0", " ")).strip(" -|,;:.")
    return texto or None


_CIDADES = {
    "ipatinga": "Ipatinga", "timoteo": "Timóteo", "coronel fabriciano": "Coronel Fabriciano",
    "santana do paraiso": "Santana do Paraíso", "belo oriente": "Belo Oriente",
    "mesquita": "Mesquita", "joanesia": "Joanésia", "bugre": "Bugre",
    "marlieria": "Marliéria", "caratinga": "Caratinga",
}
_LIXO_BAIRRO = {"aluguel", "alugar", "locacao", "locação", "imovel", "imóvel", "residencial",
                 "comercial", "mg", "minas gerais", "brasil", "nao informado", "não informado", "consulte"}
_MARCADORES_ENDERECO = re.compile(r"\b(rua|avenida|av\.?|rodovia|estrada|travessa|praca|praça|numero|nº|cep)\b", re.I)
_MARCADORES_DESCRICAO = re.compile(
    r"\b(para\s+alugu[ea]r|quartos?|su[ií]te|vagas?|m[²2]|comercial)\b", re.I
)
_MARCADORES_NAO_LOCALIZACAO = re.compile(
    r"R\$|\b(aluguel|alugar|loca[cç][aã]o|venda|vender|pre[cç]o|valor|c[oó]d(?:igo)?)\b",
    re.I,
)
_MARCADORES_NAVEGACAO = re.compile(
    r"\b(previous|next|anterior|pr[oó]xim[oa]|p[aá]gina|page|‹|›|«|»)\b|\{\{",
    re.I,
)


def eh_bairro_valido(valor):
    """Impede que títulos e características de imóveis virem opções de bairro."""
    texto = limpar_texto(valor)
    return bool(
        texto
        and len(texto) <= 55
        and not _MARCADORES_DESCRICAO.search(texto)
        and not _MARCADORES_NAO_LOCALIZACAO.search(texto)
        and not _MARCADORES_NAVEGACAO.search(texto)
    )


def normalizar_cidade(valor):
    texto = limpar_texto(valor)
    if not texto:
        return None
    chave = _sem_acento(texto).lower()
    chave = re.sub(r"\b(mg|minas gerais|brasil)\b", " ", chave)
    chave = re.sub(r"\s+", " ", chave).strip(" ,-/")
    if chave in _CIDADES:
        return _CIDADES[chave]
    for nome, canonica in _CIDADES.items():
        if re.search(rf"(?:^|\W){re.escape(nome)}(?:$|\W)", chave):
            return canonica
    return texto.title()


def _cidade_explicita(*valores):
    for valor in valores:
        texto = limpar_texto(valor)
        if not texto:
            continue
        chave = _sem_acento(texto).lower()
        for nome, canonica in _CIDADES.items():
            if re.search(rf"(?:^|\W){re.escape(nome)}(?:$|\W)", chave):
                return canonica
    return None


def cidade_explicita_em_texto(*valores):
    """Lê cidade explicitamente escrita no anúncio, inclusive fora da região-base."""
    for valor in valores:
        texto = limpar_texto(valor)
        if not texto:
            continue
        for padrao in (
            r"(?:[|,]|\s[-–—]\s)\s*([^|,/]+?)\s*(?:[-,/]\s*)(?:MG|minas gerais|[A-Z]{2})\b",
            r"\bem\s+([^|,/]+?)\s*/\s*(?:MG|minas gerais|[A-Z]{2})\b",
        ):
            encontrados = list(re.finditer(padrao, texto, re.I))
            if not encontrados:
                continue
            cidade = limpar_texto(encontrados[-1].group(1))
            if cidade:
                cidade = limpar_texto(re.split(r"\s[-–—]\s", cidade)[-1])
            if cidade and 2 <= len(cidade) <= 60 and not _MARCADORES_DESCRICAO.search(cidade):
                return normalizar_cidade(cidade)
    return None


def normalizar_localizacao(bairro, cidade, cidade_padrao=None):
    """Separa bairro e cidade e descarta rua/texto genérico como bairro."""
    bairro_original = limpar_texto(bairro)
    cidade_normalizada = (
        _cidade_explicita(bairro_original, cidade)
        or cidade_explicita_em_texto(bairro_original, cidade)
        or normalizar_cidade(cidade)
        or normalizar_cidade(cidade_padrao)
    )
    if not bairro_original:
        return None, cidade_normalizada
    bairro_limpo = re.sub(r"^(bairro|localiza[cç][aã]o|endere[cç]o)\s*:\s*", "", bairro_original, flags=re.I)
    for nome in _CIDADES:
        bairro_limpo = re.sub(rf"\s*[,|/-]?\s*{re.escape(nome)}\s*(?:[-,/|]\s*(?:mg|minas gerais|[a-z]{{2}}))?\s*$", "", bairro_limpo, flags=re.I)
    if cidade_normalizada:
        bairro_limpo = re.sub(
            rf"\s*[,|/-]?\s*{re.escape(cidade_normalizada)}\s*(?:[-,/|]\s*(?:minas gerais|[a-z]{{2}}))?\s*$",
            "",
            bairro_limpo,
            flags=re.I,
        )
    bairro_limpo = re.sub(r"\s*[-,/|]\s*(?:minas gerais|brasil|[a-z]{2})\s*$", "", bairro_limpo, flags=re.I)
    bairro_limpo = limpar_texto(bairro_limpo)
    if not bairro_limpo:
        return None, cidade_normalizada
    chave = _sem_acento(bairro_limpo).lower()
    if chave in _LIXO_BAIRRO or _MARCADORES_ENDERECO.search(bairro_limpo) or not eh_bairro_valido(bairro_limpo):
        return None, cidade_normalizada
    if cidade_normalizada and chave == _sem_acento(cidade_normalizada).lower():
        return None, cidade_normalizada
    return bairro_limpo.title(), cidade_normalizada


_IMOBILIARIAS = {"diferencialimoveis.com": "Diferencial Imóveis", "diferencial imoveis": "Diferencial Imóveis"}


def normalizar_imobiliaria(valor):
    texto = limpar_texto(valor)
    if not texto:
        return None
    return _IMOBILIARIAS.get(_sem_acento(texto).lower(), texto)
