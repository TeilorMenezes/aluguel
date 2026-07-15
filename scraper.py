"""
Scraper genérico, configurável por site via sites_config.yaml.

Usa Playwright (navegador headless) porque os sites-alvo carregam a lista
de imóveis via JavaScript (não é possível raspar com requests simples).

Suporta dois tipos de paginação, configurados por site:
  - "botao": clica repetidamente num botão "ver mais" até não haver mais
  - "url":   incrementa um parâmetro {pagina} na URL da listagem
"""
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import yaml
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import db
from detector import detectar_seletores, salvar_padrao
from geocode import geocodificar_bairro
from tipos import normalizar_tipo

CONFIG_PATH = Path(__file__).parent / "sites_config.yaml"


def carregar_config():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
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


def _parse_preco(texto: str):
    """Converte 'R$ 1.200,00  Código. 6089' -> 1200.0 (pega só o 1º número)."""
    if not texto:
        return None
    # Prioriza o valor após R$ para não confundir código do imóvel, área ou quartos com preço.
    m = re.search(r"R\$\s*([\d\.]+(?:,\d{2})?)", texto, re.IGNORECASE)
    if not m:
        m = re.search(r"[\d\.]+,\d{2}|\d+", texto)
    if not m:
        return None
    numeros = (m.group(1) if m.lastindex else m.group(0)).replace(".", "").replace(",", ".")
    try:
        return float(numeros)
    except ValueError:
        return None


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
    m = re.match(padrao, texto.strip(), re.IGNORECASE)
    if m:
        grupos = m.groupdict()
        for chave in resultado:
            if chave in grupos and grupos[chave]:
                resultado[chave] = grupos[chave].strip().title()
    return resultado


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
    for seletor in ("h1", "h2", "h3", "h4", "h5", "h6", "[class*='title']", "[class*='titulo']"):
        texto = _texto(_selecionar(card, seletor))
        if texto and not re.search(r"R\$\s*[\d\.]", texto, re.IGNORECASE):
            return texto
    if link_el:
        texto = _texto(link_el) or link_el.get_attribute("title")
        if texto and not re.search(r"R\$\s*[\d\.]", texto, re.IGNORECASE):
            return texto
    imagem = _selecionar(card, "img")
    return imagem.get_attribute("alt") if imagem else None


def _qualidade_extracao(itens):
    """Mede se título e preço foram preenchidos em uma quantidade aceitável de cards."""
    if not itens:
        return 0.0
    titulos = sum(bool(i.get("titulo")) and i["titulo"] != "Imóvel para alugar" for i in itens) / len(itens)
    precos = sum(i.get("preco") is not None for i in itens) / len(itens)
    return min(titulos, precos)


def _extrair_com_autocorrecao(page, cfg_site):
    """Extrai e, se os campos essenciais falharem, aprende novos seletores.

    A correção só é aceita quando a nova extração melhora objetivamente a
    proporção de títulos e preços preenchidos. Assim, um palpite ruim não
    substitui uma configuração que já funciona.
    """
    itens_originais = _extrair_cards(page, cfg_site)
    qualidade_original = _qualidade_extracao(itens_originais)
    if qualidade_original >= 0.8:
        return itens_originais

    try:
        sugestao = detectar_seletores(page.content())
        novos_seletores = sugestao.get("seletores", {})
        if sugestao.get("erro") or not {"card", "link", "preco"}.issubset(novos_seletores):
            return itens_originais

        seletores_anteriores = cfg_site["seletores"]
        cfg_site["seletores"] = {**seletores_anteriores, **novos_seletores}
        itens_corrigidos = _extrair_cards(page, cfg_site)
        if _qualidade_extracao(itens_corrigidos) > qualidade_original:
            salvar_padrao(sugestao.get("plataforma", "generico"), cfg_site["seletores"])
            return itens_corrigidos
        cfg_site["seletores"] = seletores_anteriores
    except Exception:
        pass
    return itens_originais


def _enriquecer_itens_incompletos(page, itens, limite=15):
    """Recupera dados na página individual somente quando o card é incompleto."""
    pendentes = [
        item for item in itens
        if item.get("preco") is None or not item.get("titulo") or item["titulo"] == "Imóvel para alugar" or not item.get("tipo")
    ][:limite]
    for item in pendentes:
        detalhe = None
        try:
            detalhe = page.context.new_page()
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
            valor = next((bruto.get(campo) for campo in ("valor", "valoraluguel", "valor_aluguel", "valorlocacao") if bruto.get(campo) is not None), None)
            itens.append({
                "url": url,
                "titulo": bruto.get("titulo") or f"{bruto.get('tipo') or 'Imóvel'} para alugar",
                "tipo": normalizar_tipo(bruto.get("tipo")),
                "preco": _parse_preco(str(valor)) if valor is not None else None,
                "bairro": bruto.get("bairro"),
                "cidade": bruto.get("cidade") or cfg_site.get("cidade_padrao"),
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
            link_el = card.query_selector(seletores["link"]) if seletores.get("link") else card
            href = link_el.get_attribute("href") if link_el else None
            url_imovel = urljoin(cfg_site["base_url"], href) if href else None
            if not url_imovel:
                continue

            titulo_detectado = _texto(_selecionar(card, seletores.get("titulo")))
            preco_detectado = _texto(_selecionar(card, seletores.get("preco")))
            bairro_txt = _texto(_selecionar(card, seletores.get("bairro")))
            tipo_txt = _texto(_selecionar(card, seletores.get("tipo")))
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

            thumb_el = _selecionar(card, seletores.get("thumbnail"))
            thumb_attr = seletores.get("thumbnail_attr", "src")
            thumb_url = thumb_el.get_attribute(thumb_attr) if thumb_el else None
            if thumb_url:
                thumb_url = urljoin(cfg_site["base_url"], thumb_url.strip())

            extraido = _aplicar_titulo_regex(titulo, cfg_site.get("titulo_regex"))
            endereco_extraido = _aplicar_endereco_regex(bairro_txt, cfg_site.get("endereco_regex"))

            bairro = endereco_extraido["bairro"] or bairro_txt or extraido["bairro"]
            cidade = endereco_extraido["cidade"] or extraido["cidade"] or cfg_site.get("cidade_padrao")
            tipo = normalizar_tipo(tipo_txt or extraido["tipo"])

            itens.append({
                "url": url_imovel,
                "titulo": titulo,
                "tipo": tipo,
                "preco": _parse_preco(preco_txt),
                "bairro": bairro,
                "cidade": cidade,
                "thumbnail_url": thumb_url,
            })
        except Exception:
            continue  # ignora um card com erro e segue nos demais

    return itens


def _raspar_com_botao(page, cfg_site: dict, pag_cfg: dict):
    botao_sel = pag_cfg.get("botao_selector")
    max_cliques = pag_cfg.get("max_cliques", 10)
    espera_ms = pag_cfg.get("espera_apos_clique_ms", 1500)

    for _ in range(max_cliques):
        botao = page.query_selector(botao_sel) if botao_sel else None
        if not botao or not botao.is_visible():
            break
        try:
            botao.click()
        except Exception:
            break
        page.wait_for_timeout(espera_ms)

    return _enriquecer_itens_incompletos(page, _extrair_com_autocorrecao(page, cfg_site))


def _raspar_com_paginacao_url(playwright, cfg_site: dict, pag_cfg: dict, headless: bool):
    pagina = pag_cfg.get("pagina_inicial", 1)
    max_paginas = pag_cfg.get("max_paginas", 20)
    todos_itens = []
    urls_vistas = set()

    browser = playwright.chromium.launch(headless=headless)
    page = browser.new_page(user_agent="Mozilla/5.0 (compatible; ImoveisScraperApp/1.0)")

    try:
        for _ in range(max_paginas):
            url_pagina = cfg_site["listagem_url"].format(pagina=pagina)
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
            pagina += 1
        return _enriquecer_itens_incompletos(page, todos_itens)
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

    if tipo_paginacao == "url":
        return _raspar_com_paginacao_url(playwright, cfg_site, pag_cfg, headless)

    # tipo "botao" ou "nenhuma": uma única página (com ou sem cliques em "ver mais")
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

        if tipo_paginacao == "botao":
            itens = _raspar_com_botao(page, cfg_site, pag_cfg)
        else:
            itens = _enriquecer_itens_incompletos(page, _extrair_com_autocorrecao(page, cfg_site))
    finally:
        browser.close()

    return itens


def rodar_varredura(sites_filtrados=None, headless=True):
    """Executa a varredura para todos os sites configurados (ou um
    subconjunto, se sites_filtrados for passado). Salva no banco e
    geocodifica bairros novos."""
    db.init_db()
    cfg = carregar_config()
    total_coletado = 0
    erro_geral = None

    with sync_playwright() as p:
        for site_key, cfg_site in cfg["sites"].items():
            if sites_filtrados and site_key not in sites_filtrados:
                continue
            try:
                itens_brutos = _raspar_site(p, cfg_site, headless=headless)
            except Exception as e:
                erro_geral = f"{site_key}: {e}"
                continue

            urls_ativas = []
            for bruto in itens_brutos:
                lat, lon = geocodificar_bairro(bruto["bairro"], bruto["cidade"])
                item = {
                    "site_key": site_key,
                    "imobiliaria": cfg_site["nome"],
                    "logo_url": cfg_site["logo"],
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
