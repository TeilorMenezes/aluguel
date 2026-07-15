"""Detecção heurística de seletores CSS em HTML renderizado de listagens."""
import re
from collections import Counter, defaultdict

from bs4 import BeautifulSoup


PRECO_RE = re.compile(r"(?:R\$\s*)?\d{1,3}(?:\.\d{3})*(?:,\d{2})|consultar", re.I)


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

    encontrados = sum(campo in seletores for campo in ("link", "titulo", "preco", "thumbnail"))
    confianca = round(min(1.0, score_card * 0.55 + (encontrados / 4) * 0.45), 2)
    return {
        "seletores": seletores,
        "confianca": confianca,
        "cards_encontrados": quantidade,
        "aviso": "Revise os seletores antes de salvar; bairro e título podem exigir ajuste manual.",
    }
