#!/usr/bin/env python3
"""Descoberta e triagem de sites de imobiliárias.

O módulo trabalha em duas etapas:

1. encontra domínios candidatos em resultados públicos;
2. entra apenas nesses domínios, procura a melhor página interna de aluguel
   e atribui uma nota baseada em evidências reais da página.

Resultados duvidosos podem ser persistidos em quarentena para revisão. Isso
evita tanto perder candidatos quanto publicar automaticamente fontes ruins.
"""
import argparse
import csv
import re
import time
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup


MUNICIPIOS_VALE_DO_ACO = {
    "IPATINGA",
    "TIMÓTEO",
    "CORONEL FABRICIANO",
    "SANTANA DO PARAÍSO",
}
EXCLUIR_DOMINIOS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "tiktok.com",
    "youtube.com",
    "google.com",
    "google.com.br",
    "maps.google.com",
    "bing.com",
    "duckduckgo.com",
    "olx.com.br",
    "vivareal.com.br",
    "zapimoveis.com.br",
    "imovelweb.com.br",
    "chavesnamao.com.br",
    "quintoandar.com.br",
    "mercadolivre.com.br",
    "wimoveis.com.br",
    "123i.com.br",
    "cnpj.biz",
    "econodata.com.br",
    "casadosdados.com.br",
    "guiamais.com.br",
    "telelistas.net",
}
PALAVRAS_IMOBILIARIAS = (
    "imobiliaria",
    "imoveis",
    "corretor de imoveis",
    "negocios imobiliarios",
    "creci",
)
PALAVRAS_ALUGUEL = ("aluguel", "alugar", "locacao", "locar")
PALAVRAS_VENDA = ("venda", "vender", "comprar", "lancamento")
PALAVRAS_CAMINHO_IMOVEL = (
    "imovel",
    "imoveis",
    "property",
    "empreendimento",
    "aluguel",
    "alugar",
    "locacao",
)
PALAVRAS_CAMINHO_RUIM = (
    "blog",
    "noticia",
    "contato",
    "login",
    "politica",
    "privacidade",
    "favorito",
    "sobre",
)
ROTAS_COMUNS_ALUGUEL = (
    "/imoveis/para-alugar",
    "/imoveis/aluguel",
    "/imoveis-locacao",
    "/aluguel",
    "/locacao",
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ImoveisScraperApp/2.0; descoberta leve)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "pt-BR,pt;q=0.9",
}
QUARENTENA_PATH = Path(__file__).parent / "data" / "imobiliarias_quarentena.csv"
IBGE_LOCALIDADES_URL = "https://servicodados.ibge.gov.br/api/v1/localidades"

# Fontes regionais conhecidas entram como sementes, mas não recebem aprovação
# automática: todas passam pela mesma localização de listagem e validação.
SITES_INICIAIS_VALE_DO_ACO = [
    ("https://www.catedralimobiliaria.com.br/", "Coronel Fabriciano"),
    ("https://www.joaodamascenoimoveis.com.br/", "Coronel Fabriciano"),
    ("https://www.americanoimobiliaria.com.br/", "Timóteo"),
    ("https://carlaoimoveismg.com.br/", "Coronel Fabriciano"),
    ("https://www.imobiliariaportalmg.com.br/", "Timóteo"),
]

_ROBOTS_CACHE = {}


@lru_cache(maxsize=1)
def listar_estados_ibge():
    resposta = requests.get(
        f"{IBGE_LOCALIDADES_URL}/estados",
        params={"orderBy": "nome"},
        headers=HEADERS,
        timeout=20,
    )
    resposta.raise_for_status()
    return [
        {"id": item["id"], "sigla": item["sigla"], "nome": item["nome"]}
        for item in resposta.json()
    ]


@lru_cache(maxsize=32)
def listar_regioes_imediatas_ibge(uf):
    resposta = requests.get(
        f"{IBGE_LOCALIDADES_URL}/estados/{uf}/regioes-imediatas",
        headers=HEADERS,
        timeout=20,
    )
    resposta.raise_for_status()
    return [
        {"id": item["id"], "nome": item["nome"]}
        for item in resposta.json()
    ]


@lru_cache(maxsize=128)
def listar_municipios_regiao_ibge(regiao_id):
    resposta = requests.get(
        f"{IBGE_LOCALIDADES_URL}/regioes-imediatas/{regiao_id}/municipios",
        headers=HEADERS,
        timeout=20,
    )
    resposta.raise_for_status()
    return sorted(item["nome"] for item in resposta.json())


@lru_cache(maxsize=32)
def listar_municipios_estado_ibge(uf):
    resposta = requests.get(
        f"{IBGE_LOCALIDADES_URL}/estados/{uf}/municipios",
        headers=HEADERS,
        timeout=20,
    )
    resposta.raise_for_status()
    return sorted(item["nome"] for item in resposta.json())


def normalizar_texto(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    return re.sub(r"\s+", " ", texto.encode("ascii", "ignore").decode().lower()).strip()


def dominio(url):
    host = (urlparse(url).hostname or "").lower().strip(".")
    for prefixo in ("www.", "m.", "mobile."):
        if host.startswith(prefixo):
            host = host[len(prefixo):]
    return host


def dominio_excluido(host):
    return any(host == bloqueado or host.endswith("." + bloqueado) for bloqueado in EXCLUIR_DOMINIOS)


def url_canonica(url):
    """Remove fragmentos e parâmetros de rastreamento sem quebrar filtros."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query = {
        chave: valores
        for chave, valores in query.items()
        if not chave.lower().startswith(("utm_", "fbclid", "gclid"))
    }
    return urlunparse(
        (
            parsed.scheme or "https",
            parsed.netloc,
            parsed.path or "/",
            "",
            urlencode(query, doseq=True),
            "",
        )
    )


def url_resultado(href):
    """Extrai o destino de links de redirecionamento do DuckDuckGo."""
    params = parse_qs(urlparse(href).query)
    return unquote(params["uddg"][0]) if "uddg" in params else href


def _sessao():
    sessao = requests.Session()
    sessao.headers.update(HEADERS)
    return sessao


def buscar(nome, municipio, sessao=None):
    consulta = f'"{nome}" imobiliária {municipio} MG'
    return buscar_consulta(consulta, sessao=sessao)


def buscar_consulta(consulta, sessao=None, limite=12):
    sessao = sessao or _sessao()
    resposta = sessao.get(
        "https://html.duckduckgo.com/html/",
        params={"q": consulta},
        timeout=25,
    )
    resposta.raise_for_status()
    soup = BeautifulSoup(resposta.text, "html.parser")
    resultados, vistos = [], set()
    for link in soup.select("a.result__a, a[href]"):
        url = url_canonica(url_resultado(link.get("href", "")))
        host = dominio(url)
        if (
            not url.startswith(("http://", "https://"))
            or not host
            or dominio_excluido(host)
            or url in vistos
        ):
            continue
        vistos.add(url)
        resultados.append((url, link.get_text(" ", strip=True)))
        if len(resultados) >= limite:
            break
    return resultados


def pontuar(url, titulo, nome="", municipio=""):
    """Pontua um resultado de busca antes de visitar o site (0 a 100)."""
    host = dominio(url)
    if not host or dominio_excluido(host):
        return -100
    caminho = normalizar_texto(urlparse(url).path)
    texto = normalizar_texto(f"{host} {titulo} {nome}")
    score = 0
    score += min(30, sum(p in texto for p in PALAVRAS_IMOBILIARIAS) * 10)
    score += min(24, sum(p in texto for p in PALAVRAS_ALUGUEL) * 8)
    score += 4 if any(p in caminho for p in PALAVRAS_CAMINHO_IMOVEL) else 0
    score += 8 if host.endswith(".br") else 0
    score += 12 if municipio and normalizar_texto(municipio) in texto else 0

    tokens_nome = [
        token
        for token in normalizar_texto(nome).split()
        if len(token) >= 4 and token not in {"imoveis", "imobiliaria", "ltda"}
    ]
    if tokens_nome:
        score += min(20, sum(token in texto for token in tokens_nome) * 5)
    if any(p in texto for p in ("lista de empresas", "cnpj", "telefone de")):
        score -= 30
    return max(0, min(100, score))


def _permitido_por_robots(url, sessao):
    host = dominio(url)
    if not host:
        return False
    if host in _ROBOTS_CACHE:
        regras = _ROBOTS_CACHE[host]
    else:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme or 'https'}://{parsed.netloc}/robots.txt"
        regras = RobotFileParser()
        regras.set_url(robots_url)
        try:
            resposta = sessao.get(robots_url, timeout=8)
            if resposta.ok:
                regras.parse(resposta.text.splitlines())
            else:
                regras = None
        except requests.RequestException:
            regras = None
        _ROBOTS_CACHE[host] = regras
    return True if regras is None else regras.can_fetch(HEADERS["User-Agent"], url)


def _baixar_pagina(url, sessao):
    if not _permitido_por_robots(url, sessao):
        return {"erro": "Bloqueado pelo robots.txt", "url": url, "html": ""}
    try:
        resposta = sessao.get(url, timeout=22, allow_redirects=True)
        resposta.raise_for_status()
    except requests.RequestException as exc:
        return {"erro": f"Falha HTTP: {exc}", "url": url, "html": ""}
    tipo = resposta.headers.get("content-type", "").lower()
    if tipo and "html" not in tipo:
        return {"erro": f"Conteúdo não HTML ({tipo.split(';')[0]})", "url": resposta.url, "html": ""}
    return {
        "erro": "",
        "url": url_canonica(resposta.url),
        "html": resposta.text,
        "status_http": resposta.status_code,
    }


def _nome_detectado(soup, host):
    candidatos = [
        (soup.select_one('meta[property="og:site_name"]') or {}).get("content", ""),
        soup.title.get_text(" ", strip=True) if soup.title else "",
        soup.h1.get_text(" ", strip=True) if soup.h1 else "",
    ]
    for candidato in candidatos:
        candidato = re.split(r"\s+[|–—]\s+|\s+-\s+", candidato, maxsplit=1)[0].strip()
        if 3 <= len(candidato) <= 80 and normalizar_texto(candidato) not in {"inicio", "home"}:
            return candidato
    return host.split(".")[0].replace("-", " ").title()


def avaliar_pagina_imobiliaria(url, html, municipio="", nome=""):
    """Retorna nota e evidências observáveis de uma página HTML."""
    host = dominio(url)
    if not html or not host or dominio_excluido(host):
        return {
            "score_pagina": 0,
            "evidencias": [],
            "motivos": ["Página vazia ou domínio excluído."],
            "nome_detectado": host,
        }

    soup = BeautifulSoup(html, "html.parser")
    texto = normalizar_texto(soup.get_text(" ", strip=True)[:350000])
    url_texto = normalizar_texto(url)
    score, evidencias, motivos = 0, [], []

    termos_imobiliarios = sum(texto.count(p) for p in PALAVRAS_IMOBILIARIAS)
    termos_aluguel = sum(texto.count(p) for p in PALAVRAS_ALUGUEL)
    termos_venda = sum(texto.count(p) for p in PALAVRAS_VENDA)
    precos = len(re.findall(r"R\$\s*\d", texto, re.I))
    links_imoveis = 0
    for link in soup.select("a[href]"):
        href = normalizar_texto(link.get("href", ""))
        if any(p in href for p in PALAVRAS_CAMINHO_IMOVEL):
            links_imoveis += 1

    if termos_imobiliarios:
        score += min(24, 10 + termos_imobiliarios * 2)
        evidencias.append("vocabulário imobiliário")
    if termos_aluguel:
        score += min(28, 12 + termos_aluguel * 2)
        evidencias.append("ofertas ou navegação de aluguel")
    if any(p in url_texto for p in PALAVRAS_ALUGUEL):
        score += 14
        evidencias.append("URL específica de aluguel")
    if municipio and normalizar_texto(municipio) in texto:
        score += 10
        evidencias.append(f"atuação em {municipio}")
    if links_imoveis >= 3:
        score += min(12, 6 + links_imoveis // 3)
        evidencias.append("links de imóveis")
    if precos >= 3:
        score += 8
        evidencias.append("preços de imóveis")
    if len(soup.select("img")) >= 3:
        score += 4

    tokens_nome = [
        token
        for token in normalizar_texto(nome).split()
        if len(token) >= 4 and token not in {"imoveis", "imobiliaria", "ltda"}
    ]
    if tokens_nome and any(token in texto or token in host for token in tokens_nome):
        score += 8
        evidencias.append("nome empresarial compatível")

    if termos_venda >= 3 and termos_aluguel == 0:
        score -= 28
        motivos.append("A página aparenta oferecer somente venda.")
    if termos_imobiliarios == 0:
        score -= 30
        motivos.append("Não há evidência suficiente de atividade imobiliária.")
    if len(texto) < 250:
        score -= 15
        motivos.append("A página entrega pouco conteúdo no HTML inicial.")

    return {
        "score_pagina": max(0, min(100, score)),
        "evidencias": evidencias,
        "motivos": motivos,
        "nome_detectado": _nome_detectado(soup, host),
        "termos_aluguel": termos_aluguel,
        "termos_venda": termos_venda,
        "links_imoveis": links_imoveis,
        "precos_detectados": precos,
    }


def _links_listagem(soup, pagina_url):
    host = dominio(pagina_url)
    candidatos = {}
    for link in soup.select("a[href]"):
        href = link.get("href", "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = url_canonica(urljoin(pagina_url, href))
        if dominio(url) != host:
            continue
        texto = normalizar_texto(f"{href} {link.get_text(' ', strip=True)}")
        score = 0
        score += sum(p in texto for p in PALAVRAS_ALUGUEL) * 20
        score += sum(p in texto for p in PALAVRAS_CAMINHO_IMOVEL) * 5
        score -= sum(p in texto for p in PALAVRAS_CAMINHO_RUIM) * 12
        if any(p in texto for p in PALAVRAS_VENDA) and not any(p in texto for p in PALAVRAS_ALUGUEL):
            score -= 15
        if score > 0:
            candidatos[url] = max(candidatos.get(url, 0), score)
    return sorted(candidatos, key=lambda item: (-candidatos[item], len(item)))


def resolver_listagem_aluguel(url, municipio="", nome="", sessao=None, max_paginas=6):
    """Encontra e valida a melhor página de aluguel dentro de um domínio."""
    sessao = sessao or _sessao()
    inicial = _baixar_pagina(url, sessao)
    if inicial["erro"]:
        return {
            "url": url,
            "base_url": f"{urlparse(url).scheme or 'https'}://{urlparse(url).netloc}",
            "score_pagina": 0,
            "confianca": "baixa",
            "evidencias": [],
            "motivos": [inicial["erro"]],
            "nome_detectado": dominio(url),
        }

    pagina_inicial = inicial["url"]
    soup = BeautifulSoup(inicial["html"], "html.parser")
    urls = [pagina_inicial]
    urls.extend(_links_listagem(soup, pagina_inicial))

    if len(urls) == 1 or not any(any(p in normalizar_texto(u) for p in PALAVRAS_ALUGUEL) for u in urls):
        origem = f"{urlparse(pagina_inicial).scheme}://{urlparse(pagina_inicial).netloc}"
        urls.extend(urljoin(origem, rota) for rota in ROTAS_COMUNS_ALUGUEL)

    vistos, avaliacoes = set(), []
    for candidata in urls:
        candidata = url_canonica(candidata)
        if candidata in vistos or len(avaliacoes) >= max_paginas:
            continue
        vistos.add(candidata)
        pagina = inicial if candidata == pagina_inicial else _baixar_pagina(candidata, sessao)
        if pagina["erro"] or dominio(pagina["url"]) != dominio(pagina_inicial):
            continue
        avaliacao = avaliar_pagina_imobiliaria(
            pagina["url"],
            pagina["html"],
            municipio=municipio,
            nome=nome,
        )
        avaliacao["url"] = pagina["url"]
        avaliacao["html_renderizado_necessario"] = avaliacao["score_pagina"] < 35
        avaliacoes.append(avaliacao)

    if not avaliacoes:
        return {
            "url": pagina_inicial,
            "base_url": f"{urlparse(pagina_inicial).scheme}://{urlparse(pagina_inicial).netloc}",
            "score_pagina": 0,
            "confianca": "baixa",
            "evidencias": [],
            "motivos": ["Nenhuma página interna pôde ser validada."],
            "nome_detectado": dominio(pagina_inicial),
        }

    melhor = max(
        avaliacoes,
        key=lambda item: (
            item["score_pagina"],
            sum(p in normalizar_texto(item["url"]) for p in PALAVRAS_ALUGUEL),
        ),
    )
    melhor["base_url"] = (
        f"{urlparse(pagina_inicial).scheme}://{urlparse(pagina_inicial).netloc}"
    )
    melhor["confianca"] = (
        "alta"
        if melhor["score_pagina"] >= 68
        else "media"
        if melhor["score_pagina"] >= 42
        else "baixa"
    )
    return melhor


def _consultas_municipio(municipio, uf):
    cidade = municipio.title()
    return (
        f'"imobiliária" "aluguel" "{cidade}" {uf}',
        f'"imóveis para alugar" "{cidade}" {uf}',
        f'"locação" imobiliária "{cidade}" {uf}',
    )


def descobrir_urls_regiao(
    municipios,
    limite=10,
    pausa_busca=0.7,
    uf="MG",
    incluir_sementes=True,
):
    """Descobre listagens de aluguel para uma coleção de municípios."""
    uf = uf.strip().upper()
    sessao = _sessao()
    brutos = {}
    for municipio in sorted({m.strip().upper() for m in municipios if m.strip()}):
        for consulta in _consultas_municipio(municipio, uf):
            try:
                resultados = buscar_consulta(consulta, sessao=sessao, limite=10)
            except requests.RequestException:
                resultados = []
            for url, titulo in resultados:
                host = dominio(url)
                score = pontuar(url, titulo, municipio=municipio)
                if score < 18:
                    continue
                atual = brutos.get(host)
                item = {
                    "url": url,
                    "municipio": municipio.title(),
                    "score_busca": score,
                    "titulo_busca": titulo,
                    "origem": "busca_publica",
                    "estado": uf,
                    "escopo": "cidades",
                }
                if atual is None or score > atual["score_busca"]:
                    brutos[host] = item
            time.sleep(max(0.0, pausa_busca))

    if incluir_sementes and uf == "MG" and (
        set(municipios) == MUNICIPIOS_VALE_DO_ACO
        or {normalizar_texto(m) for m in municipios}
        == {normalizar_texto(m) for m in MUNICIPIOS_VALE_DO_ACO}
    ):
        for url, municipio in SITES_INICIAIS_VALE_DO_ACO:
            brutos.setdefault(
                dominio(url),
                {
                    "url": url,
                    "municipio": municipio,
                    "score_busca": 45,
                    "titulo_busca": "Fonte regional inicial",
                    "origem": "semente_regional",
                    "estado": uf,
                    "escopo": "cidades",
                },
            )

    # Inspeciona primeiro os resultados mais fortes e limita o volume de rede.
    pre_selecionados = sorted(
        brutos.values(),
        key=lambda item: (-item["score_busca"], item["url"]),
    )[: max(18, limite * 2)]

    candidatos = []
    for bruto in pre_selecionados:
        resolvido = resolver_listagem_aluguel(
            bruto["url"],
            municipio=bruto["municipio"],
            sessao=sessao,
        )
        score_final = round(
            bruto["score_busca"] * 0.35 + resolvido["score_pagina"] * 0.65
        )
        item = {
            **bruto,
            **resolvido,
            "score": score_final,
            "dominio": dominio(resolvido["base_url"]),
        }
        if score_final >= 28:
            candidatos.append(item)

    unicos = {}
    for item in candidatos:
        host = item["dominio"]
        if host not in unicos or item["score"] > unicos[host]["score"]:
            unicos[host] = item
    return sorted(
        unicos.values(),
        key=lambda item: (-item["score"], item["dominio"]),
    )[:limite]


def descobrir_urls_vale_aco(limite=10):
    return descobrir_urls_regiao(MUNICIPIOS_VALE_DO_ACO, limite=limite, uf="MG")


def descobrir_urls_estado(uf, nome_estado, limite=10):
    """Faz uma busca ampla pelo estado.

    Como o resultado estadual não permite confirmar sozinho a cidade atendida
    pela imobiliária, os candidatos retornam sem ``municipio`` e devem passar
    por quarentena antes da publicação.
    """
    candidatos = descobrir_urls_regiao(
        [nome_estado],
        limite=limite,
        uf=uf,
        incluir_sementes=False,
    )
    for candidato in candidatos:
        candidato["municipio"] = ""
        candidato["estado"] = uf.upper()
        candidato["escopo"] = "estado"
    return candidatos


def registrar_quarentena(itens, caminho=QUARENTENA_PATH):
    """Atualiza a quarentena por domínio, preservando o histórico útil."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    campos = [
        "dominio",
        "nome",
        "municipio",
        "url",
        "score_descoberta",
        "confianca_detector",
        "qualidade_extracao",
        "motivo",
        "evidencias",
        "ultima_verificacao",
    ]
    existentes = {}
    if caminho.is_file():
        with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
            for linha in csv.DictReader(arquivo):
                if linha.get("dominio"):
                    existentes[linha["dominio"]] = linha

    agora = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    for item in itens:
        host = item.get("dominio") or dominio(item.get("url", ""))
        if not host:
            continue
        existentes[host] = {
            "dominio": host,
            "nome": item.get("nome") or item.get("nome_detectado") or host,
            "municipio": item.get("municipio", ""),
            "url": item.get("url", ""),
            "score_descoberta": item.get("score", ""),
            "confianca_detector": item.get("confianca_detector", ""),
            "qualidade_extracao": item.get("qualidade_extracao", ""),
            "motivo": item.get("motivo", ""),
            "evidencias": "; ".join(item.get("evidencias", [])),
            "ultima_verificacao": agora,
        }

    with caminho.open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(
            sorted(existentes.values(), key=lambda item: item["dominio"])
        )
    return caminho


def empresas_ativas(caminho):
    with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
        for linha in csv.DictReader(arquivo):
            cidade = (linha.get("municipio") or "").strip().upper()
            if cidade in MUNICIPIOS_VALE_DO_ACO and linha.get("situacao_cadastral") == "02":
                yield linha


def main():
    parser = argparse.ArgumentParser(
        description="Encontra e valida sites candidatos de imobiliárias."
    )
    parser.add_argument("csv_cnpj", type=Path, help="CSV produzido pelo filtro de CNPJ")
    parser.add_argument(
        "--saida",
        type=Path,
        default=Path("data/sites_candidatos_vale_aco.csv"),
    )
    parser.add_argument(
        "--pausa",
        type=float,
        default=1.0,
        help="Segundos entre buscas (padrão: 1,0)",
    )
    args = parser.parse_args()
    if not args.csv_cnpj.is_file():
        raise SystemExit(f"Arquivo não encontrado: {args.csv_cnpj}")

    sessao = _sessao()
    encontrados = []
    vistos = set()
    for empresa in empresas_ativas(args.csv_cnpj):
        nome = (empresa.get("nome_fantasia") or empresa.get("razao_social") or "").strip()
        chave = (nome.upper(), empresa["municipio"].upper())
        if not nome or chave in vistos:
            continue
        vistos.add(chave)
        try:
            resultados = buscar(nome, empresa["municipio"], sessao=sessao)
        except requests.RequestException as erro:
            print(f"[AVISO] Busca falhou para {nome}: {erro}")
            time.sleep(args.pausa)
            continue

        aprovados_empresa = 0
        for url, titulo in resultados[:5]:
            score_busca = pontuar(url, titulo, nome, empresa["municipio"])
            if score_busca < 22:
                continue
            resolvido = resolver_listagem_aluguel(
                url,
                municipio=empresa["municipio"],
                nome=nome,
                sessao=sessao,
            )
            score = round(score_busca * 0.35 + resolvido["score_pagina"] * 0.65)
            if score < 35:
                continue
            encontrados.append(
                {
                    "nome": nome,
                    "municipio": empresa["municipio"],
                    "cnpj": empresa["cnpj"],
                    "url": resolvido["url"],
                    "base_url": resolvido["base_url"],
                    "score": score,
                    "confianca": resolvido["confianca"],
                    "titulo_busca": titulo,
                    "evidencias": "; ".join(resolvido["evidencias"]),
                }
            )
            aprovados_empresa += 1
        print(f"[OK] {nome}: {aprovados_empresa} candidato(s) validado(s)")
        time.sleep(args.pausa)

    unicos = {}
    for item in encontrados:
        host = dominio(item["base_url"])
        if host not in unicos or item["score"] > unicos[host]["score"]:
            unicos[host] = item

    args.saida.parent.mkdir(parents=True, exist_ok=True)
    campos = [
        "nome",
        "municipio",
        "cnpj",
        "url",
        "base_url",
        "score",
        "confianca",
        "titulo_busca",
        "evidencias",
    ]
    with args.saida.open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(
            sorted(unicos.values(), key=lambda item: (-item["score"], item["nome"]))
        )
    print(f"[OK] {len(unicos)} sites candidatos salvos em {args.saida}")


if __name__ == "__main__":
    main()
