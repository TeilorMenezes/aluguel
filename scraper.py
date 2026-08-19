"""
Scraper genérico, configurável por site via sites_config.yaml.

Usa Playwright (navegador headless) porque os sites-alvo carregam a lista
de imóveis via JavaScript (não é possível raspar com requests simples).

Suporta dois tipos de paginação, configurados por site:
  - "botao": clica repetidamente num botão "ver mais" até não haver mais
  - "url":   incrementa um parâmetro {pagina} na URL da listagem
"""
import json
import re
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, quote, urljoin, urlparse, urlsplit, urlunsplit

import yaml
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import db
from detector import avaliar_extracao, detectar_seletores
from geocode import geocodificar_bairro
from tipos import normalizar_tipo
from normalizacao import cidade_explicita_em_texto, normalizar_cidade, normalizar_localizacao
from qualidade_locacao import revisar_anuncio_locacao

CONFIG_PATH = Path(__file__).parent / "sites_config.yaml"
DEFAULT_OVERRIDE_PATH = Path(__file__).parent / "public_data" / "selectors_override.yaml"
_OVERRIDE_LOCK = threading.Lock()


def _extrair_url_css(valor):
    """Retorna a URL de um valor CSS ``url(...)`` ou ``background: url(...)``."""
    if not valor:
        return None
    match = re.search(r"url\(\s*(['\"]?)(.*?)\1\s*\)", str(valor), re.I)
    return match.group(2).strip() if match and match.group(2) else None


def _normalizar_url_imagem(url):
    """Codifica nomes de arquivo da CDN sem alterar a URL de origem.

    A Imoview publica fotos com espaços, vírgulas e acentos no caminho. Ao
    abrir a URL diretamente o navegador costuma corrigir isso, mas um ``img``
    incorporado pode não fazê-lo de forma consistente.
    """
    if not url:
        return None
    # Alguns temas WordPress guardam o estilo inteiro no atributo escolhido,
    # em vez de uma URL. Extraia somente o valor de url(...).
    valor_css = _extrair_url_css(url)
    if valor_css:
        url = valor_css
    elif re.search(r"\bbackground(?:-image)?\b|\burl\s*\(", str(url), re.I):
        # Não deixe uma declaração CSS incompleta chegar ao banco ou à UI.
        return None
    partes = urlsplit(url.strip())
    return urlunsplit((
        partes.scheme, partes.netloc, quote(partes.path, safe="/%"),
        quote(partes.query, safe="=&/%"), partes.fragment,
    ))


def _primeira_url_srcset(value):
    if not value:
        return None
    candidatos = []
    for indice, parte in enumerate(value.split(",")):
        tokens = parte.strip().split()
        if not tokens:
            continue
        url = tokens[0]
        descritor = tokens[1] if len(tokens) > 1 else ""
        tamanho = re.search(r"(\d+(?:\.\d+)?)\s*(w|x)$", descritor, re.I)
        peso = float(tamanho.group(1)) if tamanho else 0
        candidatos.append((peso, -indice, url))
    return max(candidatos)[2] if candidatos else None


def _url_imagem_elemento(elemento, atributo_preferido="src"):
    """Extrai imagem de img/picture ou de um contêiner com fundo CSS."""
    if not elemento:
        return None
    candidatos = [elemento]
    try:
        descendente = elemento.query_selector("img, source")
        if descendente:
            candidatos.append(descendente)
    except Exception:
        pass
    atributos = (
        atributo_preferido, "currentSrc", "src", "data-src", "data-lazy-src",
        "data-original", "data-background-image", "data-bg", "data-bg-src",
        "srcset", "data-srcset",
    )
    for candidato in candidatos:
        for atributo in dict.fromkeys(atributos):
            if atributo == "style":
                continue
            try:
                valor = candidato.get_attribute(atributo)
            except Exception:
                valor = None
            if not valor or valor.startswith("data:image"):
                continue
            if atributo.endswith("srcset"):
                valor = _primeira_url_srcset(valor)
            if valor:
                return valor.strip()
        try:
            style = candidato.get_attribute("style") or ""
        except Exception:
            style = ""
        imagem_css = _extrair_url_css(style)
        if imagem_css:
            return imagem_css
    return None


def _eh_arquivo_de_imagem(url: str) -> bool:
    """Evita confundir o link de uma foto com a página do imóvel."""
    if not url:
        return False
    return bool(re.search(r"\.(?:avif|gif|jpe?g|png|svg|webp)(?:$|[?#])", url, re.IGNORECASE))


def _cidade_da_url(url):
    """Usa uma cidade explicitamente codificada no caminho da listagem."""
    partes = [parte for parte in urlsplit(url or "").path.split("/") if parte]
    if not partes:
        return None
    candidato = partes[-1].replace("-", " ").replace("_", " ").strip()
    if (
        not re.fullmatch(r"[A-Za-zÀ-ÿ ]{3,60}", candidato)
        or candidato.casefold() in {
            "aluguel", "alugar", "imoveis", "imóveis", "pesquisa imoveis",
            "pesquisa imóveis", "busca", "resultados", "mg", "br",
        }
    ):
        return None
    return normalizar_cidade(candidato)


def _link_do_imovel(card, seletor_preferido):
    """Escolhe um link de anúncio, ignorando âncoras que abrem somente fotos."""
    candidatos = []
    preferido = _selecionar(card, seletor_preferido)
    if preferido:
        candidatos.append(preferido)
    candidatos.extend(card.query_selector_all("a[href]"))
    vistos = set()
    for link in candidatos:
        href = link.get_attribute("href")
        if not href or href in vistos:
            continue
        vistos.add(href)
        if not _eh_arquivo_de_imagem(href):
            return link
    return None


def carregar_config():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    override_path = Path(os.getenv("IMOVEIS_SELECTORS_OVERRIDE", DEFAULT_OVERRIDE_PATH))
    if override_path.is_file():
        overrides = yaml.safe_load(override_path.read_text(encoding="utf-8")) or {}
        for site_key, learned in (overrides.get("sites") or {}).items():
            if site_key not in config.get("sites", {}):
                required = {"nome", "base_url", "listagem_url", "seletores"}
                if required.issubset(learned):
                    config.setdefault("sites", {})[site_key] = {
                        key: value for key, value in learned.items()
                        if key != "aprendido_em"
                    }
                else:
                    continue
            site = config["sites"][site_key]
            if learned.get("listagem_url"):
                site["listagem_url"] = learned["listagem_url"]
            if learned.get("seletores"):
                site["seletores"] = {
                    **(site.get("seletores") or {}),
                    **learned["seletores"],
                }
            if learned.get("espera_seletor"):
                site["espera_seletor"] = learned["espera_seletor"]
            if learned.get("paginacao"):
                site["paginacao"] = {
                    **(site.get("paginacao") or {}),
                    **learned["paginacao"],
                }
            if learned.get("filtros"):
                site["filtros"] = learned["filtros"]
    # Se a antiga descoberta automática ainda existir no arquivo de uma sessão
    # anterior, ignore-a: a fonte oficial usa a integração imoview_api.
    for chave, site in list(config["sites"].items()):
        host = urlparse(site.get("base_url", "")).netloc.removeprefix("www.")
        if host == "diferencialimoveis.com" and site.get("integracao") != "imoview_api":
            del config["sites"][chave]
    return config


def _texto(elemento):
    if elemento is None:
        return None
    txt = elemento.inner_text().strip()
    return txt if txt else None


def _normalizar_numero_preco(numero: str):
    """Converte formatos brasileiro e internacional sem reduzir milhares a decimais."""
    numero = re.sub(r"\s+", "", numero or "")
    if not re.fullmatch(r"\d[\d.,]*", numero):
        return None

    pontos = numero.count(".")
    virgulas = numero.count(",")
    if pontos and virgulas:
        decimal = "." if numero.rfind(".") > numero.rfind(",") else ","
        milhares = "," if decimal == "." else "."
        numero = numero.replace(milhares, "").replace(decimal, ".")
    elif pontos or virgulas:
        separador = "." if pontos else ","
        partes = numero.split(separador)
        if len(partes) > 1 and all(len(parte) == 3 for parte in partes[1:]):
            numero = "".join(partes)
        else:
            numero = numero.replace(separador, ".")
    try:
        return float(numero)
    except ValueError:
        return None


def _parse_preco(texto: str, *, permitir_inteiro_livre: bool = False):
    """Converte 'R$ 1.200,00  Código. 6089' -> 1200.0 (pega só o 1º número)."""
    if not texto:
        return None
    if re.search(r"\bsob\s+consulta\b|\bconsultar\b", texto, re.IGNORECASE):
        return None
    # Prioriza o valor após R$ para não confundir código do imóvel, área ou quartos com preço.
    valores_monetarios = list(re.finditer(r"R\$\s*(\d[\d\s.,]*)", texto, re.IGNORECASE))
    if valores_monetarios:
        classificados = []
        for ocorrencia in valores_monetarios:
            inicio, fim = ocorrencia.span()
            inicio_trecho = max(texto.rfind(separador, 0, inicio) for separador in "|;\n") + 1
            finais = [texto.find(separador, fim) for separador in "|;\n"]
            fim_trecho = min((posicao for posicao in finais if posicao >= 0), default=len(texto))
            contexto = texto[inicio_trecho:fim_trecho].casefold()
            score = 0
            if re.search(r"alugu|loca[cç]|mensal|rent", contexto):
                score += 4
            if re.search(r"venda|vend[ae]|compra", contexto):
                score -= 5
            if re.search(r"condom[ií]nio|iptu|taxa", contexto):
                score -= 4
            classificados.append((score, -inicio, ocorrencia.group(1)))
        melhor_score, _, melhor_valor = max(classificados)
        if melhor_score < 0 or (
            re.search(r"venda|vend[ae]|compra", texto, re.I)
            and not re.search(r"alugu|loca[cç]|mensal|rent", texto, re.I)
        ):
            return None
        return _normalizar_numero_preco(melhor_valor)

    m = None
    if not m:
        # Sem símbolo monetário, um valor com centavos é mais confiável que
        # o primeiro inteiro do card (quartos, vagas ou área).
        m = re.search(r"\d[\d\s.,]*[.,]\d{2}\b", texto)
    if not m:
        # Alguns portais exibem milhares como "2.000" sem R$ nem centavos.
        m = re.search(r"\d{1,3}(?:[.,]\d{3})+", texto)
    if not m and permitir_inteiro_livre:
        m = re.search(r"\d+", texto)
    if not m:
        return None
    return _normalizar_numero_preco(m.group(1) if m.lastindex else m.group(0))


def _aplicar_titulo_regex(titulo: str, padrao: str):
    """Aplica a regex nomeada (grupos tipo/bairro/cidade) configurada por
    site sobre o texto do título e retorna um dict com o que encontrar."""
    resultado = {"tipo": None, "bairro": None, "cidade": None}
    if not titulo or not padrao:
        return resultado
    m = re.match(padrao, titulo.strip(), re.IGNORECASE)
    if m:
        grupos = m.groupdict()
        for chave in resultado:
            if chave in grupos and grupos[chave]:
                resultado[chave] = grupos[chave].strip().title()
    return resultado


def _aplicar_endereco_regex(texto: str, padrao: str):
    """Aplica uma regex nomeada (grupos bairro/cidade) sobre um texto de
    endereço (ex: 'Bom Retiro, Ipatinga - MG') vindo de um campo separado
    do título."""
    resultado = {"bairro": None, "cidade": None}
    if not texto or not padrao:
        return resultado
    m = re.search(padrao, texto.strip(), re.IGNORECASE)
    if m:
        grupos = m.groupdict()
        for chave in resultado:
            if chave in grupos and grupos[chave]:
                resultado[chave] = grupos[chave].strip().title()
    return resultado


def _texto_seguro(elemento):
    """Lê texto de elementos opcionais, inclusive scripts JSON-LD."""
    if elemento is None:
        return None
    try:
        texto = elemento.inner_text()
    except Exception:
        try:
            texto = elemento.text_content()
        except Exception:
            texto = None
    return texto.strip() if texto and texto.strip() else None


def _enderecos_estruturados(valor):
    """Percorre JSON-LD sem presumir o formato usado por cada portal."""
    if isinstance(valor, list):
        for item in valor:
            yield from _enderecos_estruturados(item)
        return
    if not isinstance(valor, dict):
        return

    endereco = valor.get("address")
    if isinstance(endereco, dict):
        yield endereco
    if any(chave in valor for chave in (
        "addressNeighborhood", "neighborhood", "district", "addressLocality", "addressCity",
    )):
        yield valor
    for chave in ("@graph", "mainEntity", "itemListElement"):
        if chave in valor:
            yield from _enderecos_estruturados(valor[chave])


def _valor_endereco(valor, *chaves):
    for chave in chaves:
        texto = valor.get(chave) if isinstance(valor, dict) else None
        if isinstance(texto, str) and texto.strip():
            return texto.strip()
    return None


def _normalizar_endereco_estruturado(valor, cidade_padrao=None):
    """Normaliza somente campos de localização explícitos de um JSON-LD."""
    bairro = _valor_endereco(
        valor, "addressNeighborhood", "neighborhood", "district", "bairro"
    )
    cidade = _valor_endereco(
        valor, "addressLocality", "addressCity", "city", "cidade"
    )
    return normalizar_localizacao(bairro, cidade, cidade_padrao)


def _bairro_marcado_no_titulo(texto, cidade_padrao=None):
    """Aceita somente títulos que declaram o bairro de forma explícita."""
    if not texto:
        return None, None
    encontrado = re.search(r"\b(?:no\s+|na\s+)?bairro\s+(.+)$", texto, re.I)
    if not encontrado:
        return None, None
    bairro = re.split(
        r"\s*(?:\||·|—)|\s+(?:para\s+(?:alugar|vender)|a\s+venda)\b",
        encontrado.group(1),
        maxsplit=1,
        flags=re.I,
    )[0]
    return normalizar_localizacao(bairro, None, cidade_padrao)


def _localizacao_da_pagina(page, cfg_site, bairro_atual=None, cidade_atual=None):
    """Recupera localização da página individual, priorizando dados explícitos.

    A listagem é rápida, mas frequentemente omite o bairro. Esta função usa
    somente campos com semântica de endereço (JSON-LD, microdados, endereço ou
    breadcrumb), evitando inferir bairro a partir da descrição inteira.
    """
    cidade_padrao = cidade_atual or cfg_site.get("cidade_padrao")
    candidatos = []

    try:
        scripts = page.query_selector_all('script[type="application/ld+json"]')
    except Exception:
        scripts = []
    for script in scripts:
        texto = _texto_seguro(script)
        if not texto:
            continue
        try:
            dados = json.loads(texto)
        except (TypeError, ValueError):
            continue
        for endereco in _enderecos_estruturados(dados):
            bairro, cidade = _normalizar_endereco_estruturado(endereco, cidade_padrao)
            if bairro or cidade:
                candidatos.append((100 if bairro and cidade else 90, bairro, cidade))

    seletores = (
        ("[itemprop='address']", 80),
        ("[itemprop='addressLocality']", 75),
        ("address", 75),
        ("[class*='address' i]", 70),
        ("[class*='endereco' i]", 70),
        ("[class*='localizacao' i]", 65),
        ("[class*='location' i]", 65),
        ("[class*='bairro' i]", 65),
        ("[aria-label*='endereço' i]", 65),
        ("[aria-label*='localização' i]", 65),
        ("nav[aria-label*='breadcrumb' i]", 55),
        (".breadcrumb", 55),
    )
    vistos = set()
    for seletor, confianca in seletores:
        try:
            elementos = page.query_selector_all(seletor)
        except Exception:
            continue
        for elemento in elementos[:8]:
            texto = _texto_seguro(elemento)
            if not texto or texto in vistos:
                continue
            vistos.add(texto)
            bairro, cidade = normalizar_localizacao(texto, None, cidade_padrao)
            if bairro or cidade:
                candidatos.append((confianca, bairro, cidade))

    # Alguns sites não publicam endereço para proteger o proprietário, mas o
    # próprio título diz "Bairro X". É um sinal explícito e bem mais seguro do
    # que tentar inferir qualquer palavra da descrição.
    for seletor in ("h1", "meta[property='og:title']", "meta[name='title']"):
        try:
            elementos = page.query_selector_all(seletor)
        except Exception:
            continue
        for elemento in elementos[:2]:
            texto = _texto_seguro(elemento)
            if not texto:
                try:
                    texto = elemento.get_attribute("content")
                except Exception:
                    texto = None
            bairro, cidade = _bairro_marcado_no_titulo(texto, cidade_padrao)
            if bairro:
                candidatos.append((45, bairro, cidade))

    if not candidatos:
        return None, None
    _, bairro, cidade = max(
        candidatos,
        # Para preencher bairro ausente, um bairro explícito do título é mais
        # útil que um endereço estrutural que informe somente a cidade.
        key=lambda item: (bool(item[1]), item[0], bool(item[2])),
    )
    return bairro or bairro_atual, cidade or cidade_atual or normalizar_cidade(cidade_padrao)


def _nova_pagina_detalhe(page):
    """Abre detalhe sem depender do contexto implícito de ``browser.new_page``."""
    contexto = page.context
    try:
        return contexto.new_page()
    except Exception:
        navegador = getattr(contexto, "browser", None)
        if navegador:
            return navegador.new_page()
        raise


def _selecionar(card, seletor):
    """Consulta um seletor opcional sem deixar um valor vazio invalidar o card."""
    if not seletor:
        return None
    try:
        return card.query_selector(seletor)
    except Exception:
        return None


def _texto_preco_alternativo(card):
    """Encontra o menor elemento interno que contenha um preço em reais."""
    candidatos = []
    for elemento in card.query_selector_all("*"):
        try:
            texto = _texto(elemento)
            if texto and re.search(r"R\$\s*[\d\.]", texto, re.IGNORECASE):
                candidatos.append(texto)
        except Exception:
            continue
    return min(candidatos, key=len) if candidatos else None


def _titulo_alternativo(card, link_el):
    """Tenta headings, título do link e alt da imagem antes de usar texto genérico."""
    if link_el:
        texto = _texto(link_el) or link_el.get_attribute("title")
        if (
            texto
            and len(texto.strip()) >= 8
            and texto.strip().casefold() not in {"alugar", "aluguel", "locação", "locacao", "imóvel", "imovel"}
            and not re.search(r"R\$\s*[\d\.]", texto, re.IGNORECASE)
        ):
            return texto
    for seletor in ("h1", "h2", "h3", "h4", "h5", "h6", "[class*='title']", "[class*='titulo']"):
        texto = _texto(_selecionar(card, seletor))
        if (
            texto
            and len(texto.strip()) >= 8
            and texto.strip().casefold() not in {"alugar", "aluguel", "locação", "locacao", "imóvel", "imovel"}
            and not re.search(r"R\$\s*[\d\.]", texto, re.IGNORECASE)
        ):
            return texto
    imagem = _selecionar(card, "img")
    return imagem.get_attribute("alt") if imagem else None


def _titulo_util(titulo):
    texto = (titulo or "").strip()
    return bool(
        len(texto) >= 8
        and not re.fullmatch(r"\d+\s*fotos?", texto, re.I)
        and texto.casefold() not in {"undefined", "imóvel para alugar", "imovel para alugar"}
        and "{{" not in texto
    )


def _qualidade_extracao(itens):
    """Mede se título e preço foram preenchidos em uma quantidade aceitável de cards."""
    if not itens:
        return 0.0
    titulos = sum(bool(i.get("titulo")) and i["titulo"] != "Imóvel para alugar" for i in itens) / len(itens)
    titulos = sum(_titulo_util(i.get("titulo")) for i in itens) / len(itens)
    precos = sum(i.get("preco") is not None for i in itens) / len(itens)
    return min(titulos, precos)


def _url_anuncio_valida(url):
    partes = urlsplit(url or "")
    texto = (url or "").casefold()
    return bool(
        partes.scheme in {"http", "https"}
        and partes.netloc
        and not _eh_arquivo_de_imagem(url)
        and not any(token in texto for token in ("{{", "}}", "javascript:", "whatsapp", "/share/"))
    )


def _saude_lote(itens, baseline=0):
    """Gate determinístico: aprende com o último volume saudável da fonte."""
    total = len(itens)
    if not total:
        return {
            "aceito": False,
            "motivos": ["nenhum anúncio extraído"],
            "total": 0,
            "urls_unicas": 0,
            "taxas": {},
        }
    urls = {item.get("url") for item in itens if _url_anuncio_valida(item.get("url"))}
    taxas = {
        "url": len(urls) / total,
        "titulo": sum(_titulo_util(item.get("titulo")) for item in itens) / total,
        "preco": sum(item.get("preco") is not None for item in itens) / total,
        "cidade": sum(bool(item.get("cidade")) for item in itens) / total,
        "foto": sum(bool(item.get("thumbnail_url")) for item in itens) / total,
    }
    motivos = []
    if not urls or taxas["url"] < 0.95:
        motivos.append("URLs de anúncio insuficientes ou inválidas")
    if taxas["titulo"] < 0.60:
        motivos.append("títulos úteis abaixo de 60%")
    if taxas["preco"] < 0.50:
        motivos.append("preços de aluguel confiáveis abaixo de 50%")
    if taxas["cidade"] < 0.60:
        motivos.append("cidades preenchidas abaixo de 60%")
    if baseline >= 10 and len(urls) < baseline * 0.50:
        motivos.append(f"volume caiu de {baseline} para {len(urls)} URLs")
    return {
        "aceito": not motivos,
        "motivos": motivos,
        "total": total,
        "urls_unicas": len(urls),
        "taxas": {campo: round(valor, 2) for campo, valor in taxas.items()},
    }


def _extrair_com_autocorrecao(page, cfg_site):
    """Extrai e, se os campos essenciais falharem, aprende novos seletores.

    A correção só é aceita quando a nova extração melhora objetivamente a
    proporção de títulos e preços preenchidos. Assim, um palpite ruim não
    substitui uma configuração que já funciona.
    """
    # Fontes recém-cadastradas podem iniciar sem seletores. Nesse caso, a
    # primeira varredura calibra a página antes de tentar extrair os cards.
    if not cfg_site.get("seletores", {}).get("card"):
        try:
            html = page.content()
            sugestao_inicial = detectar_seletores(html)
            essenciais = {"card", "link", "preco"}
            if essenciais.issubset(sugestao_inicial.get("seletores", {})):
                validacao = avaliar_extracao(
                    html, sugestao_inicial["seletores"], page.url
                )
                if validacao.get("qualidade_extracao", 0) < 0.62:
                    return []
                cfg_site["seletores"] = sugestao_inicial["seletores"]
            else:
                return []
        except Exception:
            return []

    itens_originais = _extrair_cards(page, cfg_site)
    qualidade_original = _qualidade_extracao(itens_originais)
    if qualidade_original >= 0.8:
        return itens_originais

    try:
        html = page.content()
        sugestao = detectar_seletores(html)
        novos_seletores = sugestao.get("seletores", {})
        if sugestao.get("erro") or not {"card", "link", "preco"}.issubset(novos_seletores):
            return itens_originais

        seletores_anteriores = cfg_site["seletores"]
        validacao_anterior = avaliar_extracao(html, seletores_anteriores, page.url)
        cfg_site["seletores"] = {**seletores_anteriores, **novos_seletores}
        validacao_nova = avaliar_extracao(html, cfg_site["seletores"], page.url)
        itens_corrigidos = _extrair_cards(page, cfg_site)
        taxas_anteriores = validacao_anterior.get("taxas_campos", {})
        taxas_novas = validacao_nova.get("taxas_campos", {})
        sem_regressao_essencial = all(
            taxas_novas.get(campo, 0) >= taxas_anteriores.get(campo, 0)
            for campo in ("link", "preco")
        )
        ganho = (
            validacao_nova.get("qualidade_extracao", 0)
            >= validacao_anterior.get("qualidade_extracao", 0) + 0.05
        )
        if sem_regressao_essencial and ganho and _qualidade_extracao(itens_corrigidos) > qualidade_original:
            return itens_corrigidos
        cfg_site["seletores"] = seletores_anteriores
    except Exception:
        pass
    return itens_originais


def _enriquecer_itens_incompletos(page, itens, cfg_site, limite=15):
    """Recupera dados na página individual somente quando o card é incompleto.

    Bairro e cidade entram no mesmo fluxo porque diversos portais só mostram o
    endereço completo no anúncio, não no card de listagem.
    """
    pendentes = [
        item for item in itens
        if (
            item.get("preco") is None
            or not item.get("titulo")
            or item["titulo"] == "Imóvel para alugar"
            or not item.get("tipo")
            or not item.get("bairro")
            or not item.get("cidade")
        )
    ][:limite]
    for item in pendentes:
        detalhe = None
        try:
            detalhe = _nova_pagina_detalhe(page)
            detalhe.goto(item["url"], timeout=45000, wait_until="domcontentloaded")
            detalhe.wait_for_timeout(1200)

            titulo = _texto(_selecionar(detalhe, "h1"))
            if not titulo:
                meta = detalhe.query_selector("meta[property='og:title']")
                titulo = meta.get_attribute("content") if meta else None
            if titulo and (not item.get("titulo") or item["titulo"] == "Imóvel para alugar"):
                item["titulo"] = titulo

            if item.get("preco") is None:
                preco_txt = _texto_preco_alternativo(detalhe)
                if not preco_txt:
                    preco_txt = _texto(detalhe.query_selector("body"))
                item["preco"] = _parse_preco(preco_txt)

            if not item.get("tipo") and item.get("titulo"):
                primeiro_termo = re.split(r"[|,–-]", item["titulo"], maxsplit=1)[0]
                item["tipo"] = normalizar_tipo(primeiro_termo)

            if not item.get("bairro") or not item.get("cidade"):
                bairro, cidade = _localizacao_da_pagina(
                    detalhe,
                    cfg_site,
                    bairro_atual=item.get("bairro"),
                    cidade_atual=item.get("cidade"),
                )
                item["bairro"] = bairro
                item["cidade"] = cidade
        except Exception:
            continue
        finally:
            if detalhe:
                detalhe.close()
    return itens


def _raspar_imoview(cfg_site: dict):
    """Coleta sites Imoview pela API pública de listagem, sem depender de HTML."""
    api_url = cfg_site["api_url"]
    max_paginas = cfg_site.get("paginacao", {}).get("max_paginas", 20)
    itens, urls_vistas = [], set()
    base_url = cfg_site["base_url"]

    for pagina in range(1, max_paginas + 1):
        payload = {
            "finalidade": "alugar", "codigocidade": "0", "codigoregiao": "0",
            "numeropagina": str(pagina), "numeroregistros": "20", "opcaoimovel": "0",
            "destaque": "0", "ordenacao": "",
        }
        resposta = requests.post(api_url, data=payload, headers={"User-Agent": "Mozilla/5.0 (compatible; ImoveisScraperApp/1.0)"}, timeout=45)
        resposta.raise_for_status()
        dados = resposta.json()
        lista = dados.get("lista", [])
        if not lista:
            break

        novos = 0
        for bruto in lista:
            codigo = bruto.get("codigo")
            slug = bruto.get("url_amigavel") or bruto.get("urlAmigavel") or ""
            url = f"{base_url}/imovel/{slug}/{codigo}" if codigo else None
            if not url or url in urls_vistas:
                continue
            urls_vistas.add(url)
            fotos = bruto.get("fotos") or []
            thumb = bruto.get("urlfotoprincipalp")
            if not thumb and fotos:
                thumb = fotos[0].get("urlp") or fotos[0].get("url")
            thumb = _normalizar_url_imagem(thumb)
            valor = next((bruto.get(campo) for campo in ("valor", "valoraluguel", "valor_aluguel", "valorlocacao") if bruto.get(campo) is not None), None)
            bairro, cidade = normalizar_localizacao(
                bruto.get("bairro"), bruto.get("cidade"), cfg_site.get("cidade_padrao")
            )
            itens.append({
                "url": url,
                "titulo": bruto.get("titulo") or f"{bruto.get('tipo') or 'Imóvel'} para alugar",
                "tipo": normalizar_tipo(bruto.get("tipo")),
                "preco": _parse_preco(str(valor), permitir_inteiro_livre=True) if valor is not None else None,
                "bairro": bairro,
                "cidade": cidade,
                "thumbnail_url": thumb,
            })
            novos += 1
        if not novos or len(lista) < 20:
            break
    return itens


def _extrair_cards(page, cfg_site: dict):
    """Extrai todos os cards visíveis na página atual e retorna uma lista
    de dicts brutos (ainda sem geocodificação)."""
    seletores = cfg_site["seletores"]
    itens = []
    cards = page.query_selector_all(seletores["card"])

    for card in cards:
        try:
            link_el = _link_do_imovel(card, seletores.get("link"))
            href = link_el.get_attribute("href") if link_el else None
            url_imovel = urljoin(cfg_site["base_url"], href) if href else None
            if not url_imovel:
                continue

            titulo_detectado = _texto(_selecionar(card, seletores.get("titulo")))
            preco_detectado = _texto(_selecionar(card, seletores.get("preco")))
            bairro_txt = _texto(_selecionar(card, seletores.get("bairro")))
            tipo_txt = _texto(_selecionar(card, seletores.get("tipo")))
            status_txt = _texto(_selecionar(card, seletores.get("status")))

            # Algumas páginas de listagem misturam venda e aluguel. Quando a
            # fonte foi configurada para aluguel, aceite somente os cards cujo
            # próprio site informa esse status — sem depender do texto do título.
            if cfg_site.get("finalidade") == "aluguel" and seletores.get("status"):
                status_normalizado = (status_txt or "").casefold()
                if not any(
                    termo in status_normalizado for termo in ("aluguel", "locaç", "locac")
                ):
                    continue
            titulo_alternativo = _titulo_alternativo(card, link_el)
            # Um seletor automático pode acertar um rótulo do card (ex.: "Alugar")
            # em vez do título. Prefira o heading/link mais descritivo quando houver.
            titulo = titulo_detectado
            if not titulo or len(titulo) < 8 or titulo.lower() in {"alugar", "imóvel", "imovel"}:
                titulo = titulo_alternativo or "Imóvel para alugar"

            # Se o seletor apontar para área, código ou um rótulo sem preço, use o
            # menor elemento interno que contenha R$, que normalmente é o valor real.
            preco_txt = preco_detectado
            if _parse_preco(preco_txt) is None:
                preco_txt = _texto_preco_alternativo(card) or preco_txt

            revisao_locacao = revisar_anuncio_locacao(
                titulo, url_imovel, _parse_preco(preco_txt), contexto_preco=preco_txt
            )
            if not revisao_locacao["publicar"]:
                continue

            thumb_el = _selecionar(card, seletores.get("thumbnail")) or _selecionar(card, "img")
            thumb_attr = seletores.get("thumbnail_attr", "src")
            thumb_url = _url_imagem_elemento(thumb_el, thumb_attr)
            if thumb_url:
                thumb_url = _normalizar_url_imagem(urljoin(cfg_site["base_url"], thumb_url.strip()))

            extraido = _aplicar_titulo_regex(titulo, cfg_site.get("titulo_regex"))
            localizacao_titulo = _aplicar_endereco_regex(titulo, cfg_site.get("bairro_regex"))
            endereco_extraido = _aplicar_endereco_regex(bairro_txt, cfg_site.get("endereco_regex"))

            cidade_explicita = cidade_explicita_em_texto(bairro_txt, titulo)
            cidade_url = _cidade_da_url(cfg_site.get("listagem_url"))
            if cfg_site.get("preferir_localizacao_titulo"):
                bairro = extraido["bairro"] or localizacao_titulo["bairro"] or endereco_extraido["bairro"] or bairro_txt
                cidade = extraido["cidade"] or localizacao_titulo["cidade"] or endereco_extraido["cidade"] or cidade_explicita or cidade_url or cfg_site.get("cidade_padrao")
            else:
                bairro = endereco_extraido["bairro"] or bairro_txt or extraido["bairro"]
                cidade = endereco_extraido["cidade"] or extraido["cidade"] or cidade_explicita or cidade_url or cfg_site.get("cidade_padrao")
            bairro, cidade = normalizar_localizacao(bairro, cidade, cfg_site.get("cidade_padrao"))
            tipo = normalizar_tipo(tipo_txt or extraido["tipo"])

            itens.append({
                "url": url_imovel,
                "titulo": titulo,
                "tipo": tipo,
                "preco": revisao_locacao["preco"],
                "bairro": bairro,
                "cidade": cidade,
                "thumbnail_url": thumb_url,
            })
        except Exception:
            continue  # ignora um card com erro e segue nos demais

    return itens


def _adicionar_itens_unicos(page, cfg_site, todos_itens, urls_vistas):
    novos = []
    for item in _extrair_com_autocorrecao(page, cfg_site):
        url = item.get("url")
        if not url or url in urls_vistas:
            continue
        urls_vistas.add(url)
        todos_itens.append(item)
        novos.append(item)
    return novos


def _raspar_com_botao(page, cfg_site: dict, pag_cfg: dict):
    botao_sel = pag_cfg.get("botao_selector")
    max_cliques = pag_cfg.get("max_cliques", 40)
    espera_ms = pag_cfg.get("espera_apos_clique_ms", 1500)
    sem_novos_limite = pag_cfg.get("parar_sem_novos", 2)
    todos_itens, urls_vistas = [], set()
    _adicionar_itens_unicos(page, cfg_site, todos_itens, urls_vistas)
    sem_novos = 0

    for _ in range(max_cliques):
        botao = page.query_selector(botao_sel) if botao_sel else None
        if not botao or not botao.is_visible():
            break
        try:
            botao.click()
        except Exception:
            break
        page.wait_for_timeout(espera_ms)
        novos = _adicionar_itens_unicos(page, cfg_site, todos_itens, urls_vistas)
        sem_novos = 0 if novos else sem_novos + 1
        if sem_novos >= sem_novos_limite:
            break

    return _enriquecer_itens_incompletos(page, todos_itens, cfg_site)


def _raspar_com_rolagem(page, cfg_site: dict, pag_cfg: dict):
    max_rolagens = pag_cfg.get("max_rolagens", 50)
    espera_ms = pag_cfg.get("espera_apos_rolagem_ms", 1400)
    sem_novos_limite = pag_cfg.get("parar_sem_novos", 3)
    todos_itens, urls_vistas = [], set()
    _adicionar_itens_unicos(page, cfg_site, todos_itens, urls_vistas)
    sem_novos = 0
    for _ in range(max_rolagens):
        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        page.wait_for_timeout(espera_ms)
        novos = _adicionar_itens_unicos(page, cfg_site, todos_itens, urls_vistas)
        sem_novos = 0 if novos else sem_novos + 1
        if sem_novos >= sem_novos_limite:
            break
    return _enriquecer_itens_incompletos(page, todos_itens, cfg_site)


def _detectar_controle_continuacao(page):
    """Localiza controles prováveis sem depender de uma plataforma específica."""
    seletores_fortes = (
        "a.scroll-load", "button.scroll-load", "a.load-more", "button.load-more",
        "[data-load-more]", "a[rel='next']", "button[aria-label*='mais' i]",
        "a[aria-label*='próxim' i]", "a[aria-label*='next' i]",
    )
    for seletor in seletores_fortes:
        try:
            candidatos = page.query_selector_all(seletor)
            if any(item.is_visible() for item in candidatos):
                return seletor
        except Exception:
            continue

    try:
        return page.evaluate(
            """
            () => {
              const rx = /^(carregar|ver|mostrar)\\s+mais(?:\\s+im[oó]veis)?$|^(pr[oó]xima|pr[oó]ximo|next)$/i;
              const stable = value => value && value.length < 70 && !/\\d{4,}/.test(value);
              const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
              for (const el of document.querySelectorAll('a,button,[role="button"]')) {
                if (!visible(el) || !rx.test((el.innerText || '').trim())) continue;
                if (stable(el.id)) return '#' + CSS.escape(el.id);
                const classes = [...el.classList].filter(stable).slice(0, 4);
                if (classes.length) return el.tagName.toLowerCase() + classes.map(c => '.' + CSS.escape(c)).join('');
              }
              const current = Number(new URL(location.href).searchParams.get('page') || new URL(location.href).searchParams.get('pagina') || 1);
              const links = [...document.querySelectorAll('a[href]')].map(a => {
                try {
                  const u = new URL(a.href, location.href);
                  return {a, u, n: Number(u.searchParams.get('page') || u.searchParams.get('pagina'))};
                } catch (_) { return null; }
              }).filter(x => x && x.n > current).sort((a,b) => a.n-b.n);
              if (links.length) {
                const href = links[0].a.getAttribute('href');
                return `a[href="${CSS.escape(href)}"]`;
              }
              return '';
            }
            """
        ) or None
    except Exception:
        return None


def _template_url_numerica(urls):
    """Infere apenas padrões de paginação realmente observados em URLs."""
    urls = [url for url in dict.fromkeys(urls or []) if url]
    if not urls:
        return None

    parsed = [urlsplit(url) for url in urls]
    query_maps = [dict(parse_qsl(item.query, keep_blank_values=True)) for item in parsed]
    preferred = ("page", "pagina", "página", "pg", "offset", "start")
    actual_keys = {
        name.casefold(): name
        for query in query_maps for name in query
    }
    for normalized_key in preferred:
        key = actual_keys.get(normalized_key)
        if not key:
            continue
        values = []
        for query in query_maps:
            value = query.get(key)
            if value is not None and str(value).isdigit():
                values.append(int(value))
        if not values:
            continue
        # Para APIs exigimos repetição; para links HTML um parâmetro de página
        # explícito já é evidência suficiente porque o próprio site o publicou.
        base = parsed[0]
        pairs = parse_qsl(base.query, keep_blank_values=True)
        query = "&".join(
            f"{quote(name, safe='[]')}="
            + ("{pagina}" if name == key else quote(value, safe="/:,[]"))
            for name, value in pairs
        )
        template = urlunsplit((base.scheme, base.netloc, base.path, query, base.fragment))
        unique_values = sorted(set(values))
        differences = [
            right - left for left, right in zip(unique_values, unique_values[1:])
            if right > left
        ]
        increment = min(differences) if differences else (
            unique_values[0] if normalized_key in {"offset", "start"} else 1
        )
        return {
            "url_template": template,
            "parametro": key,
            "paginas_observadas": unique_values,
            "incremento": max(1, increment),
        }

    for url in urls:
        parts = urlsplit(url)
        match = re.search(r"(?i)(/pages?|/paginas?|/p)/?(\d+)(?=/|$)", parts.path)
        if match:
            path = parts.path[:match.start(2)] + "{pagina}" + parts.path[match.end(2):]
            return {
                "url_template": urlunsplit(
                    (parts.scheme, parts.netloc, path, parts.query, parts.fragment)
                ),
                "parametro": "caminho",
                "paginas_observadas": [int(match.group(2))],
                "incremento": 1,
            }
    return None


def _registrar_historico_estrategia(site_key, action, strategy=None, **details):
    """Registra diagnóstico local sem criar dependência do app administrativo."""
    path = os.getenv("IMOVEIS_STRATEGY_HISTORY")
    if not path:
        return
    record = {
        "quando": datetime.now().astimezone().isoformat(timespec="seconds"),
        "site_key": site_key,
        "acao": action,
        "estrategia": strategy or {},
        **details,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _OVERRIDE_LOCK:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _estrategia_api_observada(responses, fallback, observed_items=0):
    """Promove para API somente uma sequência GET paginada e repetida."""
    get_urls = [
        item["url"] for item in responses
        if item.get("method") == "GET" and item.get("url")
    ]
    groups = {}
    for url in get_urls:
        parts = urlsplit(url)
        key = (
            parts.scheme, parts.netloc, parts.path.rstrip("/"),
            tuple(sorted(name.casefold() for name, _ in parse_qsl(parts.query))),
        )
        groups.setdefault(key, []).append(url)
    inferred = None
    observed_group = []
    for urls in groups.values():
        candidate = _template_url_numerica(urls)
        if candidate and len(candidate["paginas_observadas"]) >= 2:
            inferred, observed_group = candidate, urls
            break
    if not inferred:
        return None
    strategy = {
        "tipo": "api_aprendida",
        "url_template": inferred["url_template"],
        "pagina_inicial": min(inferred["paginas_observadas"]),
        "incremento": inferred["incremento"],
        "max_paginas": 100,
        "parar_sem_novos": 2,
        "formato": "auto",
        "fallback": fallback,
        "aprendida_automaticamente": True,
        "apis_observadas": observed_group[:10],
    }
    if observed_items:
        strategy["itens_observados"] = int(observed_items)
        strategy["min_itens_esperados"] = max(1, int(observed_items * 0.8))
    return strategy


def _salvar_paginacao_aprendida(site_key, estrategia):
    caminho = os.getenv("IMOVEIS_SELECTORS_OVERRIDE")
    filtros = estrategia.get("_filtros") if estrategia else None
    if (
        not caminho or not site_key or not estrategia
        or (estrategia.get("tipo") == "nenhuma" and not filtros)
    ):
        return
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with _OVERRIDE_LOCK:
        atual = yaml.safe_load(caminho.read_text(encoding="utf-8")) if caminho.is_file() else {}
        atual = atual or {}
        site = atual.setdefault("sites", {}).setdefault(site_key, {})
        paginacao = {key: value for key, value in estrategia.items() if key != "_filtros"}
        if paginacao.get("tipo") != "nenhuma":
            site["paginacao"] = paginacao
        if filtros:
            site["filtros"] = filtros
        site["estrategia_atualizada_em"] = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        temporario = caminho.with_suffix(caminho.suffix + ".tmp")
        temporario.write_text(
            yaml.safe_dump(atual, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        temporario.replace(caminho)
    _registrar_historico_estrategia(
        site_key, "estrategia_aprendida", paginacao, filtros=filtros or {}
    )


def _raspar_com_deteccao_automatica(page, cfg_site: dict):
    """Testa botão/próxima página e depois rolagem, medindo URLs realmente novas."""
    todos_itens, urls_vistas = [], set()
    _adicionar_itens_unicos(page, cfg_site, todos_itens, urls_vistas)
    quantidade_inicial = len(urls_vistas)
    respostas_api = []
    host_base = urlparse(cfg_site.get("base_url", "")).hostname

    def observar_resposta(resposta):
        try:
            tipo = (resposta.headers.get("content-type") or "").lower()
            url = resposta.url
            mesmo_site = urlparse(url).hostname == host_base
            if mesmo_site and ("json" in tipo or re.search(r"api|ajax|paginador|search|busca", url, re.I)):
                request = resposta.request
                registro = {
                    "url": url,
                    "method": request.method.upper(),
                    "content_type": tipo,
                }
                if registro not in respostas_api:
                    respostas_api.append(registro)
        except Exception:
            pass

    page.on("response", observar_resposta)
    seletor = _detectar_controle_continuacao(page)
    if seletor:
        href_controle = None
        try:
            controle = next(
                (item for item in page.query_selector_all(seletor) if item.is_visible()),
                None,
            )
            href_controle = controle.get_attribute("href") if controle else None
        except Exception:
            pass
        itens = _raspar_com_botao(
            page,
            cfg_site,
            {
                "botao_selector": seletor,
                "max_cliques": 50,
                "espera_apos_clique_ms": 1600,
                "parar_sem_novos": 2,
            },
        )
        vistos = {item.get("url") for item in itens if item.get("url")}
        if len(vistos) > quantidade_inicial:
            fallback = {
                "tipo": "botao",
                "botao_selector": seletor,
                "max_cliques": 50,
                "espera_apos_clique_ms": 1600,
                "parar_sem_novos": 2,
                "aprendida_automaticamente": True,
            }
            estrategia = _estrategia_api_observada(
                respostas_api, fallback, observed_items=len(vistos)
            )
            if not estrategia and href_controle:
                inferred = _template_url_numerica(
                    [urljoin(cfg_site.get("listagem_url", page.url), href_controle)]
                )
                if inferred:
                    estrategia = {
                        "tipo": "url",
                        "url_template": inferred["url_template"],
                        "pagina_inicial": 1,
                        "proxima_pagina": min(inferred["paginas_observadas"]),
                        "incremento": inferred["incremento"],
                        "max_paginas": 100,
                        "parar_sem_novos": 1,
                        "fallback": fallback,
                        "aprendida_automaticamente": True,
                    }
            estrategia = estrategia or fallback
            if respostas_api and "apis_observadas" not in estrategia:
                estrategia["apis_observadas"] = [
                    item["url"] for item in respostas_api[:10]
                ]
            return itens, estrategia

    itens_rolagem = _raspar_com_rolagem(
        page,
        cfg_site,
        {"max_rolagens": 50, "espera_apos_rolagem_ms": 1400, "parar_sem_novos": 3},
    )
    vistos_rolagem = {item.get("url") for item in itens_rolagem if item.get("url")}
    if len(vistos_rolagem) > quantidade_inicial:
        return itens_rolagem, {
            "tipo": "rolagem",
            "max_rolagens": 50,
            "espera_apos_rolagem_ms": 1400,
            "parar_sem_novos": 3,
            "aprendida_automaticamente": True,
            "apis_observadas": [item["url"] for item in respostas_api[:10]],
        }
    filtros = _detectar_filtros_divisao(page)
    if filtros:
        itens_filtrados = _raspar_com_filtros_na_pagina(
            page, cfg_site, filtros, {"tipo": "nenhuma"}
        )
        vistos_filtros = {item.get("url") for item in itens_filtrados if item.get("url")}
        if len(vistos_filtros) > quantidade_inicial:
            return itens_filtrados, {
                "tipo": "nenhuma",
                "_filtros": filtros,
                "aprendida_automaticamente": True,
            }
    return _enriquecer_itens_incompletos(page, todos_itens, cfg_site), {"tipo": "nenhuma"}


def _valor_dict(record, names):
    normalized = {str(key).casefold().replace("_", ""): value for key, value in record.items()}
    for name in names:
        value = normalized.get(name.casefold().replace("_", ""))
        if value not in (None, "", []):
            return value
    return None


def _listas_de_dicts(value):
    if isinstance(value, list):
        if value and sum(isinstance(item, dict) for item in value) >= max(1, len(value) // 2):
            yield value
        for item in value:
            yield from _listas_de_dicts(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _listas_de_dicts(item)


def _htmls_em_json(value):
    if isinstance(value, str) and "<" in value and ">" in value:
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _htmls_em_json(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _htmls_em_json(item)


def _extrair_json_generico(data, cfg_site):
    """Extrai formatos JSON comuns sem aceitar registros sem URL de anúncio."""
    best = []
    for records in _listas_de_dicts(data):
        items = []
        for record in records:
            if not isinstance(record, dict):
                continue
            raw_url = _valor_dict(
                record,
                ("url", "link", "permalink", "urlimovel", "urldetalhe", "detailurl"),
            )
            if not isinstance(raw_url, str) or _eh_arquivo_de_imagem(raw_url):
                continue
            property_url = urljoin(cfg_site["base_url"], raw_url)
            title = _valor_dict(record, ("titulo", "title", "nome", "descricao", "description"))
            raw_price = _valor_dict(
                record,
                ("preco", "price", "valor", "valoraluguel", "valorlocacao", "rent"),
            )
            image = _valor_dict(
                record,
                ("thumbnail", "thumbnailurl", "imagem", "image", "foto", "fotoprincipal"),
            )
            if isinstance(image, dict):
                image = _valor_dict(image, ("url", "src", "thumbnail"))
            neighborhood = _valor_dict(record, ("bairro", "neighborhood", "district"))
            city = _valor_dict(record, ("cidade", "city", "municipio"))
            neighborhood, city = normalizar_localizacao(
                neighborhood, city, cfg_site.get("cidade_padrao")
            )
            items.append({
                "url": property_url,
                "titulo": str(title or "Imóvel para alugar"),
                "tipo": normalizar_tipo(
                    _valor_dict(record, ("tipo", "type", "tipoimovel", "propertytype"))
                ),
                "preco": _parse_preco(str(raw_price), permitir_inteiro_livre=True) if raw_price is not None else None,
                "bairro": neighborhood,
                "cidade": city,
                "thumbnail_url": (
                    _normalizar_url_imagem(urljoin(cfg_site["base_url"], image))
                    if isinstance(image, str) else None
                ),
            })
        if len(items) > len(best):
            best = items
    return best


def _raspar_com_api_aprendida(playwright, cfg_site, pag_cfg, headless):
    """Reexecuta uma API GET aprendida; qualquer inconsistência força fallback."""
    template = pag_cfg.get("url_template")
    if not template or "{pagina}" not in template:
        raise ValueError("A API aprendida não possui um modelo de página válido.")
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (compatible; ImoveisScraperApp/1.0)"
    )
    page = context.new_page()
    all_items, seen = [], set()
    try:
        page.goto(cfg_site["listagem_url"], timeout=45000, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        _adicionar_itens_unicos(page, cfg_site, all_items, seen)
        initial_count = len(seen)
        start = int(pag_cfg.get("pagina_inicial", 2))
        max_pages = int(pag_cfg.get("max_paginas", 100))
        no_growth = 0
        increment = int(pag_cfg.get("incremento", 1))
        for index in range(max_pages):
            number = start + index * increment
            response = context.request.get(template.format(pagina=number), timeout=45000)
            if not response.ok:
                break
            content_type = (response.headers.get("content-type") or "").lower()
            body = response.body()
            extracted = []
            if "json" in content_type:
                data = json.loads(body.decode("utf-8", errors="replace"))
                extracted = _extrair_json_generico(data, cfg_site)
                if not extracted:
                    html_parts = list(_htmls_em_json(data))
                    if html_parts:
                        page.set_content(
                            "<html><body>" + "\n".join(html_parts) + "</body></html>",
                            wait_until="domcontentloaded",
                        )
                        extracted = _extrair_com_autocorrecao(page, cfg_site)
            else:
                page.set_content(body.decode("utf-8", errors="replace"), wait_until="domcontentloaded")
                extracted = _extrair_com_autocorrecao(page, cfg_site)
            new = 0
            for item in extracted:
                url = item.get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                all_items.append(item)
                new += 1
            no_growth = 0 if new else no_growth + 1
            if no_growth >= int(pag_cfg.get("parar_sem_novos", 2)):
                break
        if len(seen) <= initial_count:
            raise RuntimeError("A API aprendida não retornou anúncios novos.")
        minimum = int(pag_cfg.get("min_itens_esperados", 0))
        if minimum and len(seen) < minimum:
            raise RuntimeError(
                f"A API retornou apenas {len(seen)} anúncios; o mínimo seguro é {minimum}."
            )
        return _enriquecer_itens_incompletos(page, all_items, cfg_site)
    finally:
        browser.close()


def _detectar_filtros_divisao(page):
    """Encontra filtros publicados no DOM; não inventa valores nem URLs."""
    try:
        return page.evaluate(
            """
            () => {
              const keyword = /(bairro|cidade|municip|regi[aã]o|tipo|quarto|pre[cç]o|valor)/i;
              const stable = value => value && value.length < 70 && !/\\d{4,}/.test(value);
              const css = el => {
                if (stable(el.id)) return '#' + CSS.escape(el.id);
                const name = el.getAttribute('name');
                if (stable(name)) return `${el.tagName.toLowerCase()}[name="${CSS.escape(name)}"]`;
                const classes = [...el.classList].filter(stable).slice(0, 3);
                return el.tagName.toLowerCase() + classes.map(c => '.' + CSS.escape(c)).join('');
              };
              for (const select of document.querySelectorAll('select')) {
                const identity = [select.name, select.id, select.getAttribute('aria-label')].filter(Boolean).join(' ');
                const options = [...select.options]
                  .filter(o => o.value && o.value !== '0' && o.value !== '-1')
                  .slice(0, 60).map(o => ({value:o.value, label:(o.textContent || '').trim()}));
                if (keyword.test(identity) && options.length >= 2)
                  return {tipo:'select', seletor:css(select), opcoes:options, max_opcoes:60};
              }
              const groups = new Map();
              for (const anchor of document.querySelectorAll('a[href]')) {
                try {
                  const url = new URL(anchor.href, location.href);
                  if (url.origin !== location.origin) continue;
                  for (const [key, value] of url.searchParams) {
                    if (!keyword.test(key) || !value) continue;
                    if (!groups.has(key)) groups.set(key, new Map());
                    groups.get(key).set(value, url.href);
                  }
                } catch (_) {}
              }
              for (const [key, values] of groups) {
                if (values.size >= 2 && values.size <= 60)
                  return {tipo:'links', parametro:key, urls:[...values.values()]};
              }
              return null;
            }
            """
        )
    except Exception:
        return None


def _coletar_visualizacao_atual(page, cfg_site, pag_cfg):
    kind = (pag_cfg or {}).get("tipo", "nenhuma")
    if kind == "botao":
        return _raspar_com_botao(page, cfg_site, pag_cfg)
    if kind == "rolagem":
        return _raspar_com_rolagem(page, cfg_site, pag_cfg)
    return _enriquecer_itens_incompletos(
        page, _extrair_com_autocorrecao(page, cfg_site), cfg_site
    )


def _raspar_com_filtros_na_pagina(page, cfg_site, filter_cfg, pag_cfg):
    """Percorre opções reais de filtro e une os resultados por URL."""
    all_items, seen = [], set()
    base_url = cfg_site["listagem_url"]
    choices = []
    if filter_cfg.get("tipo") == "links":
        choices = [("url", url) for url in filter_cfg.get("urls", [])[:60]]
    elif filter_cfg.get("tipo") == "select":
        choices = [
            ("option", option.get("value"))
            for option in filter_cfg.get("opcoes", [])[: int(filter_cfg.get("max_opcoes", 60))]
            if option.get("value") not in (None, "")
        ]
    if not choices:
        return []

    # Preserva também o lote sem filtro.
    page.goto(base_url, timeout=45000, wait_until="domcontentloaded")
    page.wait_for_timeout(800)
    for item in _extrair_com_autocorrecao(page, cfg_site):
        if item.get("url") and item["url"] not in seen:
            seen.add(item["url"])
            all_items.append(item)

    for choice_type, value in choices:
        try:
            page.goto(base_url, timeout=45000, wait_until="domcontentloaded")
            if choice_type == "url":
                page.goto(value, timeout=45000, wait_until="domcontentloaded")
            else:
                page.select_option(filter_cfg["seletor"], value=str(value))
                apply_selector = filter_cfg.get("aplicar_selector")
                if apply_selector:
                    button = page.query_selector(apply_selector)
                    if button and button.is_visible():
                        button.click()
                else:
                    page.eval_on_selector(
                        filter_cfg["seletor"],
                        "el => { el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }",
                    )
            page.wait_for_timeout(int(filter_cfg.get("espera_ms", 1400)))
            for item in _coletar_visualizacao_atual(page, cfg_site, pag_cfg):
                if item.get("url") and item["url"] not in seen:
                    seen.add(item["url"])
                    all_items.append(item)
        except Exception:
            continue
    return all_items


def _raspar_com_paginacao_url(playwright, cfg_site: dict, pag_cfg: dict, headless: bool):
    pagina_inicial = int(pag_cfg.get("pagina_inicial", 1))
    incremento = int(pag_cfg.get("incremento", 1))
    proxima_pagina = int(pag_cfg.get("proxima_pagina", pagina_inicial + incremento))
    max_paginas = pag_cfg.get("max_paginas", 20)
    template = pag_cfg.get("url_template")
    todos_itens = []
    urls_vistas = set()

    browser = playwright.chromium.launch(headless=headless)
    page = browser.new_page(user_agent="Mozilla/5.0 (compatible; ImoveisScraperApp/1.0)")

    try:
        for indice in range(max_paginas):
            pagina = pagina_inicial + indice * incremento
            listagem_url = cfg_site["listagem_url"]
            if indice == 0 and template:
                url_pagina = listagem_url
            elif template:
                url_pagina = template.format(
                    pagina=proxima_pagina + (indice - 1) * incremento
                )
            elif "{pagina}" in listagem_url:
                url_pagina = listagem_url.format(pagina=pagina)
            elif pagina == pag_cfg.get("pagina_inicial", 1):
                url_pagina = listagem_url
            else:
                # Padrão do WordPress/Essential Real Estate: /imoveis/page/2/.
                partes = urlsplit(listagem_url)
                caminho = partes.path.rstrip("/") + f"/page/{pagina}/"
                url_pagina = urlunsplit((partes.scheme, partes.netloc, caminho, partes.query, partes.fragment))
            page.goto(url_pagina, timeout=45000, wait_until="networkidle")

            espera = cfg_site.get("espera_seletor")
            if espera:
                try:
                    page.wait_for_selector(espera, timeout=15000)
                except PWTimeout:
                    break  # provavelmente não há mais páginas com conteúdo

            itens_pagina = _extrair_com_autocorrecao(page, cfg_site)
            novos = [i for i in itens_pagina if i["url"] not in urls_vistas]
            if not novos:
                break

            for item in novos:
                urls_vistas.add(item["url"])
            todos_itens.extend(novos)
        return _enriquecer_itens_incompletos(page, todos_itens, cfg_site)
    finally:
        browser.close()


def _executar_acao_inicial(page, cfg_site: dict):
    """Alguns sites (ex: Certa Imóveis) só carregam os imóveis via AJAX
    depois que um botão de busca é clicado, mesmo com o filtro já
    presente na URL. Essa função clica nesse botão, se configurado.
    Quando existe mais de um elemento com o mesmo seletor (ex: um botão
    escondido dentro de um painel de "filtros avançados" e outro visível),
    clica no primeiro que estiver realmente visível na tela."""
    acao = cfg_site.get("acao_inicial")
    if not acao:
        return
    seletor = acao.get("clicar_seletor")
    if not seletor:
        return
    try:
        candidatos = page.query_selector_all(seletor)
        botao = next((b for b in candidatos if b.is_visible()), None)
        if botao:
            botao.click()
            page.wait_for_timeout(acao.get("espera_apos_clique_ms", 3000))
            espera = acao.get("espera_seletor_apos_clique") or cfg_site.get("espera_seletor")
            if espera:
                try:
                    page.wait_for_selector(espera, timeout=15000)
                except PWTimeout:
                    pass
    except Exception:
        pass


def _raspar_site(playwright, cfg_site: dict, headless=True):
    if cfg_site.get("integracao") == "imoview_api":
        return _raspar_imoview(cfg_site)

    pag_cfg = cfg_site.get("paginacao", {})
    tipo_paginacao = pag_cfg.get("tipo", "nenhuma")

    if tipo_paginacao == "api_aprendida":
        try:
            itens = _raspar_com_api_aprendida(playwright, cfg_site, pag_cfg, headless)
            _registrar_historico_estrategia(
                cfg_site.get("_site_key"), "api_reutilizada", pag_cfg,
                imoveis=len({item.get("url") for item in itens if item.get("url")}),
            )
            return itens
        except Exception as exc:
            fallback = pag_cfg.get("fallback") or {"tipo": "auto"}
            _registrar_historico_estrategia(
                cfg_site.get("_site_key"), "api_falhou_fallback_navegador", pag_cfg,
                erro=str(exc), fallback=fallback,
            )
            pag_cfg = fallback
            tipo_paginacao = fallback.get("tipo", "auto")

    if tipo_paginacao == "url":
        try:
            itens = _raspar_com_paginacao_url(playwright, cfg_site, pag_cfg, headless)
            _registrar_historico_estrategia(
                cfg_site.get("_site_key"), "paginacao_url_reutilizada", pag_cfg,
                imoveis=len({item.get("url") for item in itens if item.get("url")}),
            )
            return itens
        except Exception as exc:
            fallback = pag_cfg.get("fallback")
            if not fallback:
                raise
            _registrar_historico_estrategia(
                cfg_site.get("_site_key"), "paginacao_url_falhou_fallback", pag_cfg,
                erro=str(exc), fallback=fallback,
            )
            pag_cfg = fallback
            tipo_paginacao = fallback.get("tipo", "auto")

    # Tipos de página única, botão, rolagem ou detecção local automática.
    browser = playwright.chromium.launch(headless=headless)
    page = browser.new_page(user_agent="Mozilla/5.0 (compatible; ImoveisScraperApp/1.0)")
    try:
        page.goto(cfg_site["listagem_url"], timeout=45000, wait_until="networkidle")
        espera = cfg_site.get("espera_seletor")
        if espera:
            try:
                page.wait_for_selector(espera, timeout=15000)
            except PWTimeout:
                pass

        _executar_acao_inicial(page, cfg_site)

        auto_local = os.getenv("IMOVEIS_AUTO_PAGINATION") == "1"
        filtros = cfg_site.get("filtros") or {}
        if filtros and filtros.get("ativo", True):
            itens = _raspar_com_filtros_na_pagina(page, cfg_site, filtros, pag_cfg)
            _registrar_historico_estrategia(
                cfg_site.get("_site_key"), "filtros_reutilizados", pag_cfg,
                filtros=filtros,
                imoveis=len({item.get("url") for item in itens if item.get("url")}),
            )
        elif tipo_paginacao == "botao":
            itens = _raspar_com_botao(page, cfg_site, pag_cfg)
        elif tipo_paginacao == "rolagem":
            itens = _raspar_com_rolagem(page, cfg_site, pag_cfg)
        elif auto_local and tipo_paginacao in {"nenhuma", "auto", ""}:
            itens, estrategia = _raspar_com_deteccao_automatica(page, cfg_site)
            _salvar_paginacao_aprendida(cfg_site.get("_site_key"), estrategia)
        else:
            itens = _enriquecer_itens_incompletos(
                page, _extrair_com_autocorrecao(page, cfg_site), cfg_site
            )
    finally:
        browser.close()

    return itens


def _raspar_site_com_retentativa(
    site_key,
    cfg_site,
    headless=True,
    max_tentativas=3,
):
    ultimo_erro = None
    for tentativa in range(1, max(1, max_tentativas) + 1):
        db.registrar_status_site(
            site_key,
            "executando",
            tentativas=tentativa,
        )
        try:
            with sync_playwright() as playwright:
                itens = _raspar_site(playwright, cfg_site, headless=headless)
            return site_key, cfg_site, itens, tentativa, None
        except Exception as exc:
            ultimo_erro = str(exc)
            if tentativa < max_tentativas:
                time.sleep(min(12, 2 ** tentativa))
    return site_key, cfg_site, [], max_tentativas, ultimo_erro


def rodar_varredura(
    sites_filtrados=None,
    headless=True,
    max_workers=1,
    max_tentativas=3,
):
    """Executa a varredura para todos os sites configurados (ou um
    subconjunto, se sites_filtrados for passado). Salva no banco e
    geocodifica bairros novos."""
    db.init_db()
    cfg = carregar_config()
    total_coletado = 0
    erros = []
    selecionados = [
        (site_key, {**cfg_site, "_site_key": site_key})
        for site_key, cfg_site in cfg["sites"].items()
        if not sites_filtrados or site_key in sites_filtrados
    ]
    trabalhadores = max(1, min(int(max_workers or 1), 16, len(selecionados) or 1))

    with ThreadPoolExecutor(
        max_workers=trabalhadores,
        thread_name_prefix="coleta-imoveis",
    ) as executor:
        futuros = {
            executor.submit(
                _raspar_site_com_retentativa,
                site_key,
                cfg_site,
                headless,
                max_tentativas,
            ): site_key
            for site_key, cfg_site in selecionados
        }
        for futuro in as_completed(futuros):
            try:
                site_key, cfg_site, itens_brutos, tentativas, erro = futuro.result()
            except Exception as exc:
                site_key = futuros[futuro]
                erro = str(exc)
                erros.append(f"{site_key}: {erro}")
                db.registrar_status_site(site_key, "erro", erro=erro)
                continue
            if erro:
                erros.append(f"{site_key}: {erro}")
                db.registrar_status_site(
                    site_key,
                    "erro",
                    tentativas=tentativas,
                    erro=erro,
                )
                continue

            saude = _saude_lote(itens_brutos, db.contar_imoveis_site(site_key))
            if not saude["aceito"]:
                detalhe = "; ".join(saude["motivos"])
                erros.append(f"{site_key}: coleta degradada ({detalhe})")
                db.registrar_status_site(
                    site_key,
                    "degradado",
                    tentativas=tentativas,
                    imoveis_coletados=saude["urls_unicas"],
                    erro=detalhe,
                )
                _registrar_historico_estrategia(
                    site_key, "coleta_degradada", qualidade=saude
                )
                continue

            urls_ativas = []
            for bruto in itens_brutos:
                # Proteção final: uma foto nunca deve virar um anúncio no
                # banco, mesmo se um seletor automático tiver sido impreciso.
                if _eh_arquivo_de_imagem(bruto.get("url")):
                    continue
                lat, lon = geocodificar_bairro(bruto["bairro"], bruto["cidade"])
                item = {
                    "site_key": site_key,
                    "imobiliaria": cfg_site["nome"],
                    "logo_url": cfg_site.get("logo", ""),
                    "url": bruto["url"],
                    "titulo": bruto["titulo"],
                    "tipo": bruto["tipo"],
                    "preco": bruto["preco"],
                    "bairro": bruto["bairro"],
                    "cidade": bruto["cidade"],
                    "thumbnail_url": bruto["thumbnail_url"],
                    "latitude": lat,
                    "longitude": lon,
                    "coletado_em": datetime.now().isoformat(timespec="seconds"),
                }
                db.upsert_imovel(item)
                urls_ativas.append(item["url"])
                total_coletado += 1

            db.remover_ausentes(site_key, urls_ativas)
            db.registrar_status_site(
                site_key,
                "concluido",
                tentativas=tentativas,
                imoveis_coletados=len(urls_ativas),
            )

    erro_geral = " | ".join(erros) if erros else None
    db.registrar_execucao("varredura", total_coletado, erro_geral)
    return total_coletado, erro_geral


if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    total, erro = rodar_varredura(headless=True)
    print(f"Imóveis coletados: {total}")
    if erro:
        print(f"Erro: {erro}")
