"""Detecção heurística de seletores CSS em HTML renderizado de listagens."""
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright
import yaml

from detector_ai import suggest_selectors
from url_safety import (
    DETECTOR_USER_AGENT,
    proteger_pagina,
    validar_url_publica,
    verificar_robots,
)


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
ATRIBUTOS_IMAGEM = (
    "src", "data-src", "data-lazy-src", "data-original", "data-srcset",
    "srcset", "data-background-image", "data-bg", "data-bg-src", "style",
)
UNIDADE_AREA_RE = re.compile(r"\b\d[\d.,]*\s*(?:m[²2]|metros?\s+quadrados?)\b", re.I)
SEMANTICA_PRECO_RE = re.compile(r"(?:pre[cç]o|price|valor|aluguel|loca[cç][aã]o|rental)", re.I)
CLASSES_GENERICAS = {
    "row", "col", "container", "wrapper", "item", "active", "clearfix",
    "relative", "flex", "grid", "hidden", "visible", "loaded",
}
TERMOS_CARD = (
    "property", "imovel", "imovelcard", "listing", "listagem", "anuncio",
    "resultado", "result", "card", "thumbnail", "produto", "estate", "house",
)
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


def _classe_estavel(classe: str) -> bool:
    return bool(
        re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{1,79}", classe)
        and not re.search(r"(?:^|[-_])[a-f0-9]{8,}(?:$|[-_])", classe, re.I)
        and not re.search(r"\d{5,}", classe)
    )


def _assinaturas(tag, *, card=False):
    classes = tag.get("class") or []
    classes_seguras = sorted({classe for classe in classes if _classe_estavel(classe)})
    assinaturas = []
    if classes_seguras:
        # Uma classe estável sobrevive melhor a mudanças de layout que a lista
        # completa produzida por frameworks CSS.
        prioritarias = sorted(
            classes_seguras,
            key=lambda classe: (
                not any(termo in classe.casefold() for termo in TERMOS_CARD),
                classe.casefold() in CLASSES_GENERICAS,
                len(classe),
            ),
        )
        assinaturas.extend((tag.name, (classe,)) for classe in prioritarias[:6])
        if len(classes_seguras) > 1:
            assinaturas.append((tag.name, tuple(classes_seguras[:3])))
    if tag.name in {"a", "img", "source", "picture", "figure", "h2", "h3", "h4"}:
        assinaturas.append((tag.name, ()))
    if card and tag.name in {"article", "li"}:
        assinaturas.append((tag.name, ()))
    return list(dict.fromkeys(assinaturas))


def _assinatura(tag):
    """Compatibilidade para seletores de campos: retorna o melhor candidato."""
    return next(iter(_assinaturas(tag)), None)


def _css(assinatura):
    tag, classes = assinatura
    return tag + "".join(f".{c}" for c in classes)


def _texto(tag):
    return tag.get_text(" ", strip=True) if tag else ""


def _melhor(candidatos):
    return max(candidatos, key=lambda item: item[0], default=(0, None))


def _atributo_imagem(tag):
    if not tag:
        return ""
    for atributo in ATRIBUTOS_IMAGEM:
        valor = (tag.get(atributo) or "").strip()
        if atributo == "style":
            if re.search(r"background(?:-image)?\s*:\s*url\(", valor, re.I):
                return atributo
            continue
        if valor and not valor.startswith("data:image"):
            return atributo
    return ""


def _tem_imagem(tag):
    return bool(
        _atributo_imagem(tag)
        or any(_atributo_imagem(item) for item in tag.find_all(["img", "source"]))
    )


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
    origem = (urlparse(pagina_url).hostname or "").casefold().removeprefix("www.")

    for card in amostra:
        link = selecionar(card, "link")
        if _href_valido(link):
            href = urljoin(pagina_url, link.get("href", ""))
            destino = urlparse(href)
            destino_host = (destino.hostname or "").casefold().removeprefix("www.")
            if destino.scheme in {"http", "https"} and destino_host == origem:
                links_validos += 1
                hrefs.add(href)

        preco = selecionar(card, "preco")
        texto_preco = _texto(preco)
        identidade_preco = " ".join([
            preco.name if preco else "",
            preco.get("id", "") if preco else "",
            " ".join(preco.get("class", [])) if preco else "",
        ])
        tem_marcador_monetario = bool(re.search(r"R\$|consultar", texto_preco, re.I))
        if (
            PRECO_RE.search(texto_preco)
            and len(texto_preco) <= 100
            and not UNIDADE_AREA_RE.search(texto_preco)
            and (tem_marcador_monetario or SEMANTICA_PRECO_RE.search(identidade_preco))
        ):
            precos_validos += 1

        titulo = selecionar(card, "titulo")
        texto_titulo = _texto(titulo)
        if 4 <= len(texto_titulo) <= 220:
            titulos_validos += 1

        imagem = selecionar(card, "thumbnail")
        if imagem and _tem_imagem(imagem):
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
        and taxas["titulo"] >= 0.5
        and taxas["thumbnail"] >= 0.35
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
        for assinatura in _assinaturas(tag, card=True):
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
        taxa_imagem = sum(_tem_imagem(t) for t in tags) / len(tags)
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
        classes_assinatura = assinatura[1]
        if any(
            termo in classe.casefold()
            for classe in classes_assinatura
            for termo in TERMOS_CARD
        ):
            score += 0.22
        if classes_assinatura and all(
            classe.casefold() in CLASSES_GENERICAS
            or re.match(r"^(?:col|grid|flex|container)(?:[-_]|$)", classe, re.I)
            for classe in classes_assinatura
        ):
            score -= 0.28
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

    def candidatos_desc(filtro, base=0.0, pontuador=None):
        encontrados = defaultdict(list)
        bonus = defaultdict(list)
        for card in tags_card:
            vistos = set()
            for tag in card.find_all(True):
                if not filtro(tag):
                    continue
                for assinatura in _assinaturas(tag):
                    if assinatura not in vistos:
                        encontrados[assinatura].append(card)
                        bonus[assinatura].append(pontuador(tag) if pontuador else 0.0)
                        vistos.add(assinatura)
        return [(base + len(cards_com_tag) / quantidade + sum(bonus[assinatura]) / max(1, len(bonus[assinatura])), assinatura)
                for assinatura, cards_com_tag in encontrados.items()]

    def score_link(tag):
        href = (tag.get("href") or "").casefold()
        classes = " ".join(tag.get("class") or []).casefold()
        text = _texto(tag).casefold()
        score = 0.0
        if CAMINHO_IMOVEL_RE.search(href):
            score += 0.55
        if 8 <= len(text) <= 180:
            score += 0.16
        if tag.find(["img", "picture"]):
            score += 0.12
        if re.search(r"compar|compare|favorit|share|whatsapp|mapa|next|pagina", href + " " + classes):
            score -= 0.8
        return score

    _, link = _melhor(candidatos_desc(
        lambda t: t.name == "a"
        and _href_valido(t)
        and (
            CAMINHO_IMOVEL_RE.search(t.get("href", ""))
            or 4 <= len(_texto(t)) <= 220
            or bool(t.find("img"))
        ),
        0.15,
        score_link,
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
        lambda t: (
            0.45 if any(
                termo in " ".join(t.get("class") or []).casefold()
                for termo in ("preco", "price", "valor", "aluguel", "rent")
            ) else 0.0
        ) + (0.12 if t.name in {"span", "p", "strong", "b"} else 0.0)
        - (0.25 if t.name == "a" and len(_texto(t)) > 100 else 0.0),
    ))
    _, thumbnail = _melhor(candidatos_desc(
        lambda t: bool(_atributo_imagem(t)) or (
            t.name in {"picture", "figure"} and _tem_imagem(t)
        ),
        0.1,
    ))
    if not thumbnail:
        cards_com_imagem_unica = [
            card
            for card in tags_card
            if len([img for img in card.find_all(["img", "source"]) if _atributo_imagem(img)]) == 1
        ]
        if len(cards_com_imagem_unica) / quantidade >= 0.5:
            thumbnail = ("img", ())
    _, titulo = _melhor(candidatos_desc(
        lambda t: t.name in {"h1", "h2", "h3", "h4", "h5", "h6"}
        and 4 <= len(_texto(t)) <= 220,
        0.15,
    ))
    if not titulo:
        _, titulo = _melhor(candidatos_desc(
            lambda t: t.name == "a"
            and _href_valido(t)
            and 8 <= len(_texto(t)) <= 220
            and not PRECO_FORTE_RE.search(_texto(t)),
            0.08,
        ))
    _, bairro = _melhor(candidatos_desc(
        lambda t: any(p in " ".join(t.get("class") or []).lower() for p in ("bairro", "endereco", "address", "local")),
        0.15,
    ))
    _, tipo = _melhor(candidatos_desc(
        lambda t: any(
            p in " ".join(t.get("class") or []).lower()
            for p in ("tipo", "type", "categoria", "category")
        ) and 3 <= len(_texto(t)) <= 100,
        0.10,
    ))

    seletores = {"card": _css(assinatura_card)}
    for campo, assinatura in (("link", link), ("titulo", titulo), ("preco", preco),
                               ("bairro", bairro), ("tipo", tipo),
                               ("thumbnail", thumbnail)):
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
        "evidencias": {
            "candidatos_card": len(cards),
            "score_card": round(score_card, 3),
            "campos_detectados": sorted(seletores),
        },
        "aviso": "Revise os seletores antes de salvar; bairro e título podem exigir ajuste manual.",
    }


def inspecionar_url(url: str, *, verify_policy: bool = True) -> dict:
    """Abre uma URL com Chromium e detecta seletores no HTML renderizado.

    O carregamento é feito com JavaScript habilitado, pois os portais de
    imóveis normalmente não entregam os cards no HTML inicial.
    """
    url = url.strip()
    if not urlparse(url).scheme:
        url = f"https://{url}"

    try:
        validar_url_publica(url)
        policy = verificar_robots(url) if verify_policy else "verificada_externamente"
        original_host = urlparse(url).hostname or ""
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=DETECTOR_USER_AGENT)
            try:
                proteger_pagina(page, url)
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
                validar_url_publica(page.url, allowed_hosts={original_host})
                page.wait_for_timeout(4000)
                def analisar_snapshot(snapshot_html):
                    analise = detectar_seletores(snapshot_html)
                    analise["url"] = page.url
                    analise["policy"] = policy
                    if not analise.get("erro"):
                        validacao = avaliar_extracao(
                            snapshot_html, analise.get("seletores", {}), page.url
                        )
                        analise.update(validacao)
                        analise["confianca_heuristica"] = analise["confianca"]
                        analise["confianca"] = round(
                            analise["confianca"] * 0.55
                            + validacao["qualidade_extracao"] * 0.45,
                            2,
                        )
                    return analise

                html = page.content()
                resultado = analisar_snapshot(html)
                melhor_chave = (
                    bool(resultado.get("publicavel")),
                    float(resultado.get("qualidade_extracao", 0)),
                    int(resultado.get("taxas_campos", {}).get("links_unicos", 0)),
                    int(resultado.get("cards_encontrados", 0)),
                )
                assinatura_estavel = None
                repeticoes_estaveis = 0
                for _ in range(4):
                    if resultado.get("publicavel"):
                        assinatura = (
                            resultado.get("seletores", {}).get("card"),
                            resultado.get("cards_encontrados"),
                            resultado.get("taxas_campos", {}).get("links_unicos"),
                        )
                        repeticoes_estaveis = repeticoes_estaveis + 1 if assinatura == assinatura_estavel else 1
                        assinatura_estavel = assinatura
                        if repeticoes_estaveis >= 2:
                            break
                    page.wait_for_timeout(1500)
                    snapshot_html = page.content()
                    candidato = analisar_snapshot(snapshot_html)
                    chave = (
                        bool(candidato.get("publicavel")),
                        float(candidato.get("qualidade_extracao", 0)),
                        int(candidato.get("taxas_campos", {}).get("links_unicos", 0)),
                        int(candidato.get("cards_encontrados", 0)),
                    )
                    if chave > melhor_chave:
                        resultado, html, melhor_chave = candidato, snapshot_html, chave
                if resultado.get("erro") or not resultado.get("publicavel"):
                    try:
                        ai = suggest_selectors(html, page.url)
                        resultado["ia"] = ai
                        if ai.get("used"):
                            ai_validation = avaliar_extracao(
                                html, ai["selectors"], page.url
                            )
                            current_quality = float(resultado.get("qualidade_extracao", 0))
                            if (
                                ai_validation.get("publicavel")
                                and ai_validation["qualidade_extracao"] > current_quality
                            ):
                                resultado.pop("erro", None)
                                resultado.update(ai_validation)
                                resultado["seletores"] = ai["selectors"]
                                resultado["confianca"] = round(
                                    ai_validation["qualidade_extracao"] * 0.9, 2
                                )
                                resultado["sugerido_por_ia"] = True
                    except Exception as exc:
                        resultado["ia"] = {"used": False, "error": str(exc)}
                return resultado
            finally:
                browser.close()
    except PWTimeout:
        return {"erro": "A página demorou demais para responder."}
    except Exception as exc:
        return {"erro": f"Não foi possível inspecionar a URL: {exc}"}
