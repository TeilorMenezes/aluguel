"""Detecção heurística de seletores CSS em HTML renderizado de listagens."""
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright
import yaml


PRECO_RE = re.compile(r"(?:R\$\s*)?\d{1,3}(?:\.\d{3})*(?:,\d{2})|consultar", re.I)
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
    return (tag.name, tuple(sorted(classes))) if classes else None


def _css(assinatura):
    tag, classes = assinatura
    return tag + "".join(f".{c}" for c in classes)


def _texto(tag):
    return tag.get_text(" ", strip=True) if tag else ""


def _melhor(candidatos):
    return max(candidatos, key=lambda item: item[0], default=(0, None))


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
        score = min(len(tags), 20) / 20 * 0.25 + min(descendentes, 25) / 25 * 0.35 + taxa_preco * 0.40
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

    _, link = _melhor(candidatos_desc(lambda t: t.name == "a" and t.get("href"), 0.0))
    _, preco = _melhor(candidatos_desc(lambda t: bool(PRECO_RE.search(_texto(t))), 0.25))
    _, thumbnail = _melhor(candidatos_desc(lambda t: t.name == "img" and t.get("src"), 0.0))
    _, titulo = _melhor(candidatos_desc(lambda t: t.name in {"h1", "h2", "h3", "h4", "h5", "h6"} and len(_texto(t)) > 3, 0.15))
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
        seletores["thumbnail_attr"] = "src"

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
                resultado = detectar_seletores(page.content())
                resultado["url"] = page.url
                return resultado
            finally:
                browser.close()
    except PWTimeout:
        return {"erro": "A página demorou demais para responder."}
    except Exception as exc:
        return {"erro": f"Não foi possível inspecionar a URL: {exc}"}
