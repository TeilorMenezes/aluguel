#!/usr/bin/env python3
"""Descobre possíveis sites de imobiliárias do Vale do Aço a partir do CNPJ.

Exemplo:
  python descobrir_sites.py data/imobiliarias_vale_aco.csv

O CSV de entrada deve ser o exportado por baixar_imobiliarias_cnpj.py.
O resultado é salvo em data/sites_candidatos_vale_aco.csv para revisão.
"""
import argparse
import csv
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup


MUNICIPIOS_VALE_DO_ACO = {"IPATINGA", "TIMÓTEO", "CORONEL FABRICIANO", "SANTANA DO PARAÍSO"}
EXCLUIR_DOMINIOS = {
    "facebook.com", "instagram.com", "linkedin.com", "google.com", "maps.google.com",
    "olx.com.br", "vivareal.com.br", "zapimoveis.com.br", "imovelweb.com.br", "youtube.com",
}
PALAVRAS_RELEVANTES = ("imóveis", "imoveis", "imobiliária", "imobiliaria", "aluguel", "locação", "locacao")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ImoveisScraperApp/1.0)"}
# Fontes locais conhecidas, usadas somente como ponto de partida quando a
# busca pública não devolver resultados (motores de busca mudam o HTML com
# frequência). Elas continuam passando pela mesma inspeção automática.
SITES_INICIAIS_VALE_DO_ACO = [
    ("https://www.catedralimobiliaria.com.br/", "Coronel Fabriciano"),
    ("https://www.joaodamascenoimoveis.com.br/", "Coronel Fabriciano"),
    ("https://www.americanoimobiliaria.com.br/", "Timóteo"),
    ("https://carlaoimoveismg.com.br/", "Coronel Fabriciano"),
    ("https://www.imobiliariaportalmg.com.br/", "Timóteo"),
]


def dominio(url):
    return urlparse(url).netloc.lower().removeprefix("www.")


def url_resultado(href):
    """Extrai o destino de links de redirecionamento do DuckDuckGo."""
    params = parse_qs(urlparse(href).query)
    return unquote(params["uddg"][0]) if "uddg" in params else href


def buscar(nome, municipio):
    consulta = f'"{nome}" imobiliária {municipio} MG'
    return buscar_consulta(consulta)


def buscar_consulta(consulta):
    resposta = requests.get("https://html.duckduckgo.com/html/", params={"q": consulta}, headers=HEADERS, timeout=25)
    resposta.raise_for_status()
    soup = BeautifulSoup(resposta.text, "html.parser")
    resultados = []
    for link in soup.select("a.result__a, a[href]"):
        url = url_resultado(link.get("href", ""))
        if url.startswith("http") and dominio(url) not in {"duckduckgo.com", "html.duckduckgo.com"}:
            resultados.append((url, link.get_text(" ", strip=True)))
    return resultados


def descobrir_urls_vale_aco(limite=5):
    """Pesquisa portais de aluguel públicos na região, sem exigir CSV de CNPJ.

    Retorna poucos candidatos para evitar consultas e inspeções excessivas.
    """
    candidatos = {}
    for municipio in sorted(MUNICIPIOS_VALE_DO_ACO):
        try:
            resultados = buscar_consulta(f"imobiliária imóveis para alugar {municipio.title()} MG")
        except requests.RequestException:
            continue
        for url, titulo in resultados:
            score = pontuar(url, titulo, "")
            host = dominio(url)
            if score >= 3 and host not in candidatos:
                candidatos[host] = {"url": url, "municipio": municipio.title(), "score": score, "titulo": titulo}
        time.sleep(1.0)
    for url, municipio in SITES_INICIAIS_VALE_DO_ACO:
        candidatos.setdefault(dominio(url), {"url": url, "municipio": municipio, "score": 4, "titulo": "Fonte regional inicial"})
    return sorted(candidatos.values(), key=lambda item: (-item["score"], item["url"]))[:limite]


def pontuar(url, titulo, nome):
    host = dominio(url)
    if not host or any(host == bloqueado or host.endswith("." + bloqueado) for bloqueado in EXCLUIR_DOMINIOS):
        return -1
    texto = f"{host} {titulo} {nome}".lower()
    score = sum(palavra in texto for palavra in PALAVRAS_RELEVANTES) * 2
    score += 1 if ".br" in host else 0
    return score


def empresas_ativas(caminho):
    with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
        for linha in csv.DictReader(arquivo):
            cidade = (linha.get("municipio") or "").strip().upper()
            if cidade in MUNICIPIOS_VALE_DO_ACO and linha.get("situacao_cadastral") == "02":
                yield linha


def main():
    parser = argparse.ArgumentParser(description="Encontra sites candidatos de imobiliárias do Vale do Aço.")
    parser.add_argument("csv_cnpj", type=Path, help="CSV produzido pelo filtro de CNPJ")
    parser.add_argument("--saida", type=Path, default=Path("data/sites_candidatos_vale_aco.csv"))
    parser.add_argument("--pausa", type=float, default=1.5, help="Segundos entre buscas (padrão: 1,5)")
    args = parser.parse_args()
    if not args.csv_cnpj.is_file():
        raise SystemExit(f"Arquivo não encontrado: {args.csv_cnpj}")

    args.saida.parent.mkdir(parents=True, exist_ok=True)
    vistos, encontrados = set(), []
    for empresa in empresas_ativas(args.csv_cnpj):
        nome = (empresa.get("nome_fantasia") or empresa.get("razao_social") or "").strip()
        chave = (nome.upper(), empresa["municipio"].upper())
        if not nome or chave in vistos:
            continue
        vistos.add(chave)
        try:
            candidatos = [(pontuar(url, titulo, nome), url, titulo) for url, titulo in buscar(nome, empresa["municipio"])]
        except requests.RequestException as erro:
            print(f"[AVISO] Busca falhou para {nome}: {erro}")
            time.sleep(args.pausa)
            continue
        for score, url, titulo in candidatos:
            if score >= 3:
                encontrados.append({"nome": nome, "municipio": empresa["municipio"], "cnpj": empresa["cnpj"], "url": url, "score": score, "titulo_busca": titulo})
        print(f"[OK] {nome}: {sum(score >= 3 for score, _, _ in candidatos)} candidato(s)")
        time.sleep(args.pausa)

    unicos = {}
    for item in encontrados:
        unicos.setdefault(dominio(item["url"]), item)
    with args.saida.open("w", encoding="utf-8-sig", newline="") as arquivo:
        campos = ["nome", "municipio", "cnpj", "url", "score", "titulo_busca"]
        escritor = csv.DictWriter(arquivo, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(sorted(unicos.values(), key=lambda x: (-x["score"], x["nome"])))
    print(f"[OK] {len(unicos)} sites candidatos salvos em {args.saida}")


if __name__ == "__main__":
    main()
