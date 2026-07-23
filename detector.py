"""Detecção heurística de seletores CSS em HTML renderizado de listagens."""
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright
import yaml


PRECO_RE = re.compile(
    r"(?:R\$\s*\d[\d.\s]*(?:,\d{2})?|"
    r"\d{1,3}(?:\.\d{3})+(?:,\d{2})?|consultar)",
    re.I,
)
PRECO_FORTE_RE = re.compile(
    r"(?:R\$\s*\d[\d.\s]*(?:,\d{2})?|consultar|"
    r"\d{1,3}(?:\.\d{3})+(?:,\d{2})?)",
    re.I,
)
ALUGUEL_RE = re.compile(r"\b(?:aluguel|alugar|loca(?:ç|c)[aã]o|locar)\b", re.I)
VENDA_RE = re.compile(r"\b(?:venda|vender|comprar)\b", re.I)
CAMINHO_IMOVEL_RE = re.compile(
    r"(?:imovel|imóveis?|property|detalhe|aluguel|alugar|loca(?:ç|c)[aã]o)",
    re.I,
)
ATRIBUTOS_IMAGEM = ("src", "data-src", "data-lazy-src", "data-original")
PADROES_PATH = Path(__file__).parent / "detector_patterns.yaml"


def identificar_plataforma(html: str) -> str:
    """Reconhece plataformas já vistas, sem depender do domínio do site."""
    conteudo = html.lower()
    if "imoview.com.br" in conteudo or "retornar-imoveis-disponiveis" in conteudo:
        return "imoview"
    if "universalsoftware" in conteudo:
        return "universal_software"
    if "wp-content" in conteudo or "wordpress" in conteudo:
        return "wordpress"
    if "imoveloffice" in conteudo:
        return "imoveloffice"
    return "generico"


def _carregar_padroes() -> dict:
    if not PADROES_PATH.is_file():
        return {"plataformas": {}}
    return yaml.safe_load(PADROES_PATH.read_text(encoding="utf-8")) or {"plataformas": {}}


def salvar_padrao(plataforma: str, seletores: dict) -> None:
    """Registra seletores validados pelo administrador para reuso futuro."""
    dados = _carregar_padroes()
    dados.setdefault("plataformas", {})[plataforma] = {
        "seletores": {chave: valor for chave, valor in seletores.items() if valor},
    }
    PADROES_PATH.write_text(yaml.safe_dump(dados, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _padrao_valido(soup, padrao: dict) -> dict:
    """Usa um padrão aprendido somente se ele ainda funcionar no HTML atual."""
    seletores = padrao.get("seletores", {})
    card_sel = seletores.get("card")
    if not card_sel:
        return {}
    try:
        cards = soup.select(card_sel)
        if not cards:
            return {}
        validos = {"card": card_sel}
        for campo, seletor in seletores.items():
            if campo in {"card", "thumbnail_attr"}:
                continue
            if cards[0].select_one(seletor):
                validos[campo] = seletor
        if "thumbnail_attr" in seletores and "thumbnail" in validos:
            validos["thumbnail_attr"] = seletores["thumbnail_attr"]
        return validos if {"link", "preco"}.issubset(validos) else {}
    except Exception:
        return {}


def _assinatura(tag):
    classes = tag.get("class") or []
    classes_seguras = [
        classe for classe in classes
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", classe)
    ]
    return (tag.name, tuple(sorted(classes_seguras))) if classes_seguras else None


def _css(assinatura):
    tag, classes = assinatura
    return tag + "".join(f".{c}" for c in classes)


def _texto(tag):
    return tag.get_text(" ", strip=True) if tag else ""


def _melhor(candidatos):
    return max(candidatos, key=lambda item: item[0], default=(0, None))


def _atributo_imagem(tag):
    if not tag or tag.name != "img":
        return ""
    for atributo in ATRIBUTOS_IMAGEM:
        valor = (tag.get(atributo) or "").strip()
        if valor and not valor.startswith("data:image"):
            return atributo
    return ""


def _href_valido(tag):
    href = (tag.get("href") or "").strip() if tag else ""
    return bool(
        href
        and not href.startswith(("#", "javascript:", "mailto:", "tel:"))
    )


def avaliar_extracao(html: str, seletores: dict, pagina_url: str = "") -> dict:
    """Mede se os seletores produzem cards utilizáveis, não apenas elementos.

    A confiança heurística identifica padrões repetidos. Esta segunda etapa
    valida os dados extraídos de uma amostra para impedir o cadastro automático
    de menus, carrosséis, notícias ou páginas exclusivas de venda.
    """
    soup = BeautifulSoup(html, "html.parser")
    motivos = []
    try:
        cards = soup.select(seletores.get("card", ""))
    except Exception:
        cards = []

    if not cards:
        return {
            "qualidade_extracao": 0.0,
            "publicavel": False,
            "eh_listagem_aluguel": False,
            "motivos_validacao": ["O seletor de card não retornou elementos."],
            "taxas_campos": {},
        }

    amostra = cards[: min(24, len(cards))]

    def selecionar(card, campo):
        seletor = seletores.get(campo)
        if not seletor:
            return None
        try:
            return card.select_one(seletor)
        except Exception:
            return None

    links_validos = 0
    precos_validos = 0
    titulos_validos = 0
    imagens_validas = 0
    hrefs = set()

    for card in amostra:
        link = selecionar(card, "link")
        if _href_valido(link):
            href = urljoin(pagina_url, link.get("href", ""))
            if urlparse(href).scheme in {"http", "https"}:
                links_validos += 1
                hrefs.add(href)

        preco = selecionar(card, "preco")
        texto_preco = _texto(preco)
        if PRECO_RE.search(texto_preco) and len(texto_preco) <= 100:
            precos_validos += 1

        titulo = selecionar(card, "titulo")
        texto_titulo = _texto(titulo)
        if 4 <= len(texto_titulo) <= 220:
            titulos_validos += 1

        imagem = selecionar(card, "thumbnail")
        if _atributo_imagem(imagem):
            imagens_validas += 1

    total = len(amostra)
    taxas = {
        "link": round(links_validos / total, 2),
        "preco": round(precos_validos / total, 2),
        "titulo": round(titulos_validos / total, 2),
        "thumbnail": round(imagens_validas / total, 2),
        "links_unicos": len(hrefs),
    }

    texto_pagina = soup.get_text(" ", strip=True)
    url_normalizada = pagina_url.lower()
    ocorrencias_aluguel = len(ALUGUEL_RE.findall(texto_pagina[:300000]))
    ocorrencias_venda = len(VENDA_RE.findall(texto_pagina[:300000]))
    aluguel_na_url = bool(ALUGUEL_RE.search(url_normalizada))
    eh_listagem_aluguel = bool(
        aluguel_na_url
        or (
            ocorrencias_aluguel >= 2
            and ocorrencias_aluguel >= max(1, ocorrencias_venda)
        )
    )

    quantidade_score = min(1.0, len(cards) / 8)
    qualidade = (
        taxas["link"] * 0.30
        + taxas["preco"] * 0.27
        + taxas["titulo"] * 0.18
        + taxas["thumbnail"] * 0.15
        + quantidade_score * 0.10
    )
    if len(hrefs) < min(2, total):
        qualidade *= 0.75
        motivos.append("Poucos links de anúncios distintos foram encontrados.")
    if taxas["preco"] < 0.5:
        motivos.append("Menos da metade dos cards possui preço reconhecível.")
    if taxas["titulo"] < 0.5:
        motivos.append("Menos da metade dos cards possui título utilizável.")
    if taxas["thumbnail"] < 0.35:
        motivos.append("Poucas imagens válidas foram encontradas nos cards.")
    if not eh_listagem_aluguel:
        motivos.append("A página não demonstrou ser uma listagem específica de aluguel.")

    essenciais = {"card", "link", "preco"}.issubset(seletores)
    publicavel = bool(
        essenciais
        and len(cards) >= 3
        and taxas["link"] >= 0.65
        and taxas["preco"] >= 0.5
        and max(taxas["titulo"], taxas["thumbnail"]) >= 0.5
        and eh_listagem_aluguel
        and qualidade >= 0.62
    )
    return {
        "qualidade_extracao": round(min(1.0, qualidade), 2),
        "publicavel": publicavel,
        "eh_listagem_aluguel": eh_listagem_aluguel,
        "motivos_validacao": motivos,
        "taxas_campos": taxas,
    }


def detectar_seletores(html: str) -> dict:
    """Retorna seletores prováveis e uma pontuação de confiança (0 a 1).

    O algoritmo favorece elementos repetidos que contêm vários descendentes e
    preço. Isso evita confundir um ``span.preco`` repetido com o card inteiro.
    """
    soup = BeautifulSoup(html, "html.parser")
    plataforma = identificar_plataforma(html)
    padrao_aprendido = _padrao_valido(soup, _carregar_padroes().get("plataformas", {}).get(plataforma, {}))
    grupos = defaultdict(list)
    for tag in soup.find_all(True):
        assinatura = _assinatura(tag)
        if assinatura:
            grupos[assinatura].append(tag)

    cards = []
    for assinatura, tags in grupos.items():
        if len(tags) < 3:
            continue
        descendentes = sum(len(t.find_all(True)) for t in tags) / len(tags)
        if descendentes < 3:
            continue
        taxa_preco = sum(bool(PRECO_RE.search(_texto(t))) for t in tags) / len(tags)
        taxa_link = sum(any(_href_valido(a) for a in t.find_all("a")) for t in tags) / len(tags)
        taxa_imagem = sum(any(_atributo_imagem(img) for img in t.find_all("img")) for t in tags) / len(tags)
        taxa_titulo = sum(
            any(4 <= len(_texto(h)) <= 220 for h in t.find_all(re.compile(r"^h[1-6]$")))
            for t in tags
        ) / len(tags)
        sinais = sum(taxa >= 0.4 for taxa in (taxa_preco, taxa_link, taxa_imagem, taxa_titulo))
        if sinais < 2 or taxa_link < 0.35:
            continue
        score = (
            min(len(tags), 20) / 20 * 0.12
            + min(descendentes, 25) / 25 * 0.16
            + taxa_preco * 0.30
            + taxa_link * 0.22
            + taxa_imagem * 0.10
            + taxa_titulo * 0.10
        )
        cards.append((score, assinatura, tags))

    score_card, assinatura_card, tags_card = _melhor(cards)
    if not assinatura_card:
        if padrao_aprendido:
            return {
                "seletores": padrao_aprendido,
                "confianca": 0.9,
                "cards_encontrados": len(soup.select(padrao_aprendido["card"])),
                "plataforma": plataforma,
                "padrao_aprendido": True,
                "aviso": "Seletores recuperados do padrão previamente validado.",
            }
        return {"erro": "Não foi possível identificar cards repetidos no HTML."}

    quantidade = len(tags_card)

    def candidatos_desc(filtro, base=0.0):
        encontrados = defaultdict(list)
        for card in tags_card:
            vistos = set()
            for tag in card.find_all(True):
                assinatura = _assinatura(tag)
                if assinatura and assinatura not in vistos and filtro(tag):
                    encontrados[assinatura].append(card)
                    vistos.add(assinatura)
        return [(base + len(cards_com_tag) / quantidade, assinatura)
                for assinatura, cards_com_tag in encontrados.items()]

    _, link = _melhor(candidatos_desc(
        lambda t: t.name == "a"
        and _href_valido(t)
        and (
            CAMINHO_IMOVEL_RE.search(t.get("href", ""))
            or 4 <= len(_texto(t)) <= 220
            or bool(t.find("img"))
        ),
        0.15,
    ))
    _, preco = _melhor(candidatos_desc(
        lambda t: bool(PRECO_FORTE_RE.search(_texto(t)))
        and len(_texto(t)) <= 100
        and (
            "R$" in _texto(t)
            or "consultar" in _texto(t).lower()
            or any(
                termo in " ".join(t.get("class") or []).lower()
                for termo in ("preco", "price", "valor")
            )
        ),
        0.25,
    ))
    _, thumbnail = _melhor(candidatos_desc(
        lambda t: t.name == "img" and bool(_atributo_imagem(t)),
        0.1,
    ))
    if not thumbnail:
        cards_com_imagem_unica = [
            card
            for card in tags_card
            if len([img for img in card.find_all("img") if _atributo_imagem(img)]) == 1
        ]
        if len(cards_com_imagem_unica) / quantidade >= 0.5:
            thumbnail = ("img", ())
    _, titulo = _melhor(candidatos_desc(
        lambda t: t.name in {"h1", "h2", "h3", "h4", "h5", "h6"}
        and 4 <= len(_texto(t)) <= 220,
        0.15,
    ))
    _, bairro = _melhor(candidatos_desc(
        lambda t: any(p in " ".join(t.get("class") or []).lower() for p in ("bairro", "endereco", "address", "local")),
        0.15,
    ))

    seletores = {"card": _css(assinatura_card)}
    for campo, assinatura in (("link", link), ("titulo", titulo), ("preco", preco),
                               ("bairro", bairro), ("thumbnail", thumbnail)):
        if assinatura:
            seletores[campo] = _css(assinatura)
    if thumbnail:
        primeira_imagem = next(
            (
                tag
                for card in tags_card
                for tag in card.select(_css(thumbnail))
                if _atributo_imagem(tag)
            ),
            None,
        )
        seletores["thumbnail_attr"] = _atributo_imagem(primeira_imagem) or "src"

    if padrao_aprendido:
        seletores.update(padrao_aprendido)

    encontrados = sum(campo in seletores for campo in ("link", "titulo", "preco", "thumbnail"))
    confianca = 0.9 if padrao_aprendido else round(min(1.0, score_card * 0.55 + (encontrados / 4) * 0.45), 2)
    return {
        "seletores": seletores,
        "confianca": confianca,
        "cards_encontrados": quantidade,
        "plataforma": plataforma,
        "padrao_aprendido": bool(padrao_aprendido),
        "aviso": "Revise os seletores antes de salvar; bairro e título podem exigir ajuste manual.",
    }


def inspecionar_url(url: str) -> dict:
    """Abre uma URL com Chromium e detecta seletores no HTML renderizado.

    O carregamento é feito com JavaScript habilitado, pois os portais de
    imóveis normalmente não entregam os cards no HTML inicial.
    """
    url = url.strip()
    if not urlparse(url).scheme:
        url = f"https://{url}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent="Mozilla/5.0 (compatible; ImoveisScraperApp/1.0)")
            try:
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
                page.wait_for_timeout(4000)
                html = page.content()
                resultado = detectar_seletores(html)
                resultado["url"] = page.url
                if not resultado.get("erro"):
                    validacao = avaliar_extracao(
                        html,
                        resultado.get("seletores", {}),
                        page.url,
                    )
                    resultado.update(validacao)
                    resultado["confianca_heuristica"] = resultado["confianca"]
                    resultado["confianca"] = round(
                        resultado["confianca"] * 0.55
                        + validacao["qualidade_extracao"] * 0.45,
                        2,
                    )
                return resultado
            finally:
                browser.close()
    except PWTimeout:
        return {"erro": "A página demorou demais para responder."}
    except Exception as exc:
        return {"erro": f"Não foi possível inspecionar a URL: {exc}"}
