#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
baixar_imobiliarias_cnpj.py
============================

Baixa a base de Dados Abertos de CNPJ da Receita Federal e filtra apenas
os estabelecimentos cujo CNAE corresponde a atividades imobiliárias
(corretagem, administração e compra/venda de imóveis), opcionalmente
restringindo por município.

FONTE DOS DADOS
---------------
Os dados oficiais são publicados mensalmente pela Receita Federal em:
    https://arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/
Esse endereço usa Nextcloud e bloqueia acesso automatizado simples, então
este script usa por padrão um espelho público e gratuito que replica os
mesmos arquivos com uma listagem HTML simples (Apache-style), mantido pelo
site Casa dos Dados:
    https://dados-abertos-rf-cnpj.casadosdados.com.br/arquivos/
Se preferir, troque MIRROR_BASE_URL para a URL oficial da Receita Federal
(o layout dos arquivos .zip é idêntico).

O QUE O SCRIPT FAZ
------------------
1. Descobre a pasta mais recente (mais atual) disponível no espelho.
2. Baixa as tabelas de apoio pequenas: CNAECSV (nomes dos CNAEs) e
   MUNICCSV (nomes dos municípios).
3. Baixa e processa, uma de cada vez (sem carregar tudo em memória), as
   10 partes do arquivo ESTABELE (dados de estabelecimentos), filtrando
   apenas linhas cujo CNAE fiscal principal (ou secundário) esteja na
   lista TARGET_CNAES e, se configurado, cujo município bata com
   TARGET_MUNICIPIO.
4. Baixa e processa as 10 partes do arquivo EMPRECSV (dados da empresa:
   razão social, capital social, natureza jurídica), mas SOMENTE para os
   CNPJs básicos que sobraram no filtro do passo 3 — isso evita ter que
   carregar as ~60 milhões de empresas do Brasil na memória.
5. Junta tudo e salva um único CSV final em /mnt/user-data/outputs.

Os arquivos .zip baixados são apagados após o processamento de cada parte
para não lotar o disco (cada parte pode ter várias centenas de MB).

CNAEs configurados por padrão (atividades imobiliárias mais comuns):
    6810-2/01  Compra e venda de imóveis próprios
    6810-2/02  Aluguel de imóveis próprios
    6821-8/01  Corretagem na compra e venda e avaliação de imóveis
    6821-8/02  Corretagem no aluguel de imóveis
    6822-6/00  Gestão e administração da propriedade imobiliária

USO
---
    pip install requests --break-system-packages

    # Todas as imobiliárias do Brasil (arquivo final pode ficar grande)
    python baixar_imobiliarias_cnpj.py

    # Filtrando por município (recomendado)
    python baixar_imobiliarias_cnpj.py --municipio "IPATINGA"

    # Escolhendo outros CNAEs
    python baixar_imobiliarias_cnpj.py --cnae 6822600 --cnae 6821801
"""

import argparse
import csv
import gc
import io
import os
import re
import sys
import time
import zipfile
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

import requests

# --------------------------------------------------------------------------
# CONFIGURAÇÃO
# --------------------------------------------------------------------------

MIRROR_BASE_URL = "https://dados-abertos-rf-cnpj.casadosdados.com.br/arquivos"

# CNAEs (sem pontuação/barra, só dígitos) considerados "imobiliárias".
# Pode ser sobrescrito via --cnae na linha de comando.
DEFAULT_TARGET_CNAES = {
    "6810201",  # Compra e venda de imóveis próprios
    "6810202",  # Aluguel de imóveis próprios
    "6821801",  # Corretagem na compra, venda e avaliação de imóveis
    "6821802",  # Corretagem no aluguel de imóveis
    "6822600",  # Gestão e administração da propriedade imobiliária
}

WORKDIR = "cnpj_tmp"
OUTPUT_DIR = "/mnt/user-data/outputs"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "imobiliarias_cnpj.csv")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; CNPJFilterBot/1.0)"})


# --------------------------------------------------------------------------
# DESCOBERTA DA PASTA MAIS RECENTE
# --------------------------------------------------------------------------

def descobrir_pasta_mais_recente() -> str:
    """Lê o índice HTML do espelho e retorna a URL da pasta (mês) mais recente."""
    resp = SESSION.get(MIRROR_BASE_URL + "/", timeout=60)
    resp.raise_for_status()
    # As pastas aparecem como <a href="2026-05-10/">2026-05-10/</a>
    datas = re.findall(r'href="(\d{4}-\d{2}-\d{2})/"', resp.text)
    if not datas:
        raise RuntimeError(
            "Não foi possível encontrar nenhuma pasta de data no índice do espelho. "
            "Verifique se MIRROR_BASE_URL ainda é válido."
        )
    datas_ordenadas = sorted(datas, key=lambda d: datetime.strptime(d, "%Y-%m-%d"))
    mais_recente = datas_ordenadas[-1]
    print(f"[INFO] Pasta mais recente encontrada: {mais_recente}")
    return f"{MIRROR_BASE_URL}/{mais_recente}/"


def listar_arquivos_da_pasta(pasta_url: str) -> List[str]:
    """Retorna os nomes de arquivo .zip disponíveis dentro da pasta."""
    resp = SESSION.get(pasta_url, timeout=60)
    resp.raise_for_status()
    nomes = re.findall(r'href="([^"?/]+\.zip)"', resp.text)
    return sorted(set(nomes))


# --------------------------------------------------------------------------
# DOWNLOAD
# --------------------------------------------------------------------------

def baixar_arquivo(url: str, destino: str) -> None:
    print(f"[DOWNLOAD] {url}")
    with SESSION.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        baixado = 0
        with open(destino, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                baixado += len(chunk)
                if total:
                    pct = baixado / total * 100
                    print(f"\r  {baixado/1e6:8.1f} MB / {total/1e6:8.1f} MB ({pct:5.1f}%)", end="")
        print()


def abrir_csv_dentro_do_zip(caminho_zip: str):
    """Abre o(s) arquivo(s) de dados dentro de um .zip da Receita e retorna
    um leitor de linhas de texto (encoding latin-1, como a RFB publica)."""
    zf = zipfile.ZipFile(caminho_zip)
    nome_interno = zf.namelist()[0]
    raw = zf.open(nome_interno, "r")
    texto = io.TextIOWrapper(raw, encoding="latin-1", newline="")
    return zf, raw, texto


def fechar_e_apagar(zf: zipfile.ZipFile, raw, texto, caminho_zip: str, tentativas: int = 5) -> None:
    """Fecha todos os handles abertos do zip (nessa ordem: texto, raw, zf) e
    só então tenta apagar o arquivo. No Windows (especialmente dentro de
    pastas sincronizadas pelo OneDrive) o SO pode levar uma fração de
    segundo pra liberar o arquivo depois do close, então tentamos de novo
    algumas vezes antes de desistir."""
    for obj in (texto, raw, zf):
        try:
            obj.close()
        except Exception:
            pass
    gc.collect()  # ajuda o Windows a liberar o handle mais rápido

    for tentativa in range(1, tentativas + 1):
        try:
            os.remove(caminho_zip)
            return
        except PermissionError:
            if tentativa == tentativas:
                print(f"[AVISO] Não consegui apagar '{caminho_zip}' "
                      f"(ainda em uso pelo sistema). Vou deixar esse arquivo aí "
                      f"— pode apagar manualmente depois. Prosseguindo.")
                return
            time.sleep(1.0 * tentativa)


# --------------------------------------------------------------------------
# TABELAS DE APOIO (CNAE e MUNICÍPIO)
# --------------------------------------------------------------------------

def carregar_tabela_apoio(pasta_url: str, arquivos_disponiveis: List[str], prefixo: str) -> Dict[str, str]:
    """Baixa uma tabela de apoio pequena (CNAECSV ou MUNICCSV) e devolve um
    dicionário {codigo: descricao}."""
    candidatos = [a for a in arquivos_disponiveis if prefixo in a.upper()]
    if not candidatos:
        print(f"[AVISO] Não encontrei arquivo de apoio contendo '{prefixo}'. Pulando.")
        return {}

    nome_zip = candidatos[0]
    caminho_local = os.path.join(WORKDIR, nome_zip)
    baixar_arquivo(pasta_url + nome_zip, caminho_local)

    tabela = {}
    zf, raw, texto = abrir_csv_dentro_do_zip(caminho_local)
    leitor = csv.reader(texto, delimiter=";")
    for linha in leitor:
        if len(linha) >= 2:
            codigo = linha[0].strip().strip('"')
            descricao = linha[1].strip().strip('"')
            tabela[codigo] = descricao
    fechar_e_apagar(zf, raw, texto, caminho_local)
    return tabela


# --------------------------------------------------------------------------
# PASSO 1: FILTRAR ESTABELECIMENTOS POR CNAE (E MUNICÍPIO, OPCIONAL)
# --------------------------------------------------------------------------

# Layout do arquivo ESTABELE (posições 0-indexed), conforme o
# "Novo Layout para os Dados Abertos do CNPJ" da Receita Federal:
#  0  cnpj_basico
#  1  cnpj_ordem
#  2  cnpj_dv
#  3  identificador_matriz_filial
#  4  nome_fantasia
#  5  situacao_cadastral
#  6  data_situacao_cadastral
#  7  motivo_situacao_cadastral
#  8  nome_cidade_exterior
#  9  pais
# 10  data_inicio_atividade
# 11  cnae_fiscal_principal
# 12  cnae_fiscal_secundaria
# 13  tipo_logradouro
# 14  logradouro
# 15  numero
# 16  complemento
# 17  bairro
# 18  cep
# 19  uf
# 20  municipio (código RFB, não é o código IBGE!)
# 21  ddd_1
# 22  telefone_1
# 23  ddd_2
# 24  telefone_2
# 25  ddd_fax
# 26  fax
# 27  correio_eletronico
# 28  situacao_especial
# 29  data_situacao_especial

IDX_CNPJ_BASICO = 0
IDX_CNPJ_ORDEM = 1
IDX_CNPJ_DV = 2
IDX_NOME_FANTASIA = 4
IDX_SITUACAO_CADASTRAL = 5
IDX_CNAE_PRINCIPAL = 11
IDX_CNAE_SECUNDARIA = 12
IDX_LOGRADOURO_TIPO = 13
IDX_LOGRADOURO = 14
IDX_NUMERO = 15
IDX_COMPLEMENTO = 16
IDX_BAIRRO = 17
IDX_CEP = 18
IDX_UF = 19
IDX_MUNICIPIO_COD = 20
IDX_DDD1 = 21
IDX_TEL1 = 22
IDX_EMAIL = 27

# Situação cadastral 02 = ATIVA (01 nula, 03 suspensa, 04 inapta, 08 baixada)
SITUACAO_ATIVA = "02"


def cnae_bate(linha: List[str], cnaes_alvo: Set[str]) -> bool:
    principal = linha[IDX_CNAE_PRINCIPAL].strip()
    secundarias = linha[IDX_CNAE_SECUNDARIA].strip()
    if principal in cnaes_alvo:
        return True
    if secundarias:
        for c in secundarias.split(","):
            if c.strip() in cnaes_alvo:
                return True
    return False


def processar_estabelecimentos(
    pasta_url: str,
    arquivos_disponiveis: List[str],
    cnaes_alvo: Set[str],
    codigo_municipio_alvo: Optional[str],
    apenas_ativas: bool,
) -> List[List[str]]:
    """Baixa cada parte do ESTABELE, filtra linha a linha e devolve a lista
    de linhas filtradas (mantendo todas as colunas originais)."""
    arquivos_estabele = [a for a in arquivos_disponiveis if "ESTABELE" in a.upper()]
    if not arquivos_estabele:
        raise RuntimeError("Nenhum arquivo ESTABELE encontrado na pasta remota.")

    print(f"[INFO] {len(arquivos_estabele)} arquivo(s) ESTABELE a processar.")
    resultado: List[List[str]] = []

    for i, nome_zip in enumerate(arquivos_estabele, start=1):
        caminho_local = os.path.join(WORKDIR, nome_zip)
        print(f"\n[PARTE {i}/{len(arquivos_estabele)}] {nome_zip}")
        baixar_arquivo(pasta_url + nome_zip, caminho_local)

        zf, raw, texto = abrir_csv_dentro_do_zip(caminho_local)
        leitor = csv.reader(texto, delimiter=";")
        contador = 0
        for linha in leitor:
            if len(linha) <= IDX_MUNICIPIO_COD:
                continue
            if not cnae_bate(linha, cnaes_alvo):
                continue
            if apenas_ativas and linha[IDX_SITUACAO_CADASTRAL].strip() != SITUACAO_ATIVA:
                continue
            if codigo_municipio_alvo and linha[IDX_MUNICIPIO_COD].strip() != codigo_municipio_alvo:
                continue
            resultado.append(linha)
            contador += 1
        fechar_e_apagar(zf, raw, texto, caminho_local)
        print(f"  -> {contador} estabelecimento(s) encontrados nesta parte "
              f"(total acumulado: {len(resultado)})")

    return resultado


# --------------------------------------------------------------------------
# PASSO 2: BUSCAR RAZÃO SOCIAL (ARQUIVO EMPRECSV) SÓ PARA OS CNPJS QUE SOBRARAM
# --------------------------------------------------------------------------

# Layout do arquivo EMPRECSV:
# 0 cnpj_basico
# 1 razao_social
# 2 natureza_juridica
# 3 qualificacao_responsavel
# 4 capital_social
# 5 porte_empresa
# 6 ente_federativo_responsavel

IDX_EMP_CNPJ_BASICO = 0
IDX_EMP_RAZAO_SOCIAL = 1
IDX_EMP_CAPITAL_SOCIAL = 4
IDX_EMP_PORTE = 5


def buscar_razao_social(
    pasta_url: str,
    arquivos_disponiveis: List[str],
    cnpjs_basicos_necessarios: Set[str],
) -> Dict[str, Tuple[str, str, str]]:
    """Baixa cada parte do EMPRECSV e guarda razão social/capital/porte
    apenas para os cnpj_basico que estão em cnpjs_basicos_necessarios."""
    arquivos_empresas = [a for a in arquivos_disponiveis if "EMPRESAS" in a.upper()]
    if not arquivos_empresas:
        print("[AVISO] Nenhum arquivo EMPRECSV encontrado — razão social ficará vazia.")
        return {}

    print(f"\n[INFO] {len(arquivos_empresas)} arquivo(s) EMPRECSV a processar "
          f"(buscando {len(cnpjs_basicos_necessarios)} CNPJs específicos).")
    encontrados: Dict[str, Tuple[str, str, str]] = {}
    restantes = set(cnpjs_basicos_necessarios)

    for i, nome_zip in enumerate(arquivos_empresas, start=1):
        if not restantes:
            print("[INFO] Todos os CNPJs já foram encontrados, pulando arquivos restantes.")
            break
        caminho_local = os.path.join(WORKDIR, nome_zip)
        print(f"\n[PARTE {i}/{len(arquivos_empresas)}] {nome_zip}")
        baixar_arquivo(pasta_url + nome_zip, caminho_local)

        zf, raw, texto = abrir_csv_dentro_do_zip(caminho_local)
        leitor = csv.reader(texto, delimiter=";")
        for linha in leitor:
            if len(linha) <= IDX_EMP_PORTE:
                continue
            cnpj_basico = linha[IDX_EMP_CNPJ_BASICO].strip()
            if cnpj_basico in restantes:
                encontrados[cnpj_basico] = (
                    linha[IDX_EMP_RAZAO_SOCIAL].strip(),
                    linha[IDX_EMP_CAPITAL_SOCIAL].strip(),
                    linha[IDX_EMP_PORTE].strip(),
                )
                restantes.discard(cnpj_basico)
        fechar_e_apagar(zf, raw, texto, caminho_local)
        print(f"  -> {len(encontrados)} razões sociais encontradas até agora "
              f"({len(restantes)} ainda faltando)")

    return encontrados


# --------------------------------------------------------------------------
# MONTAGEM DO CSV FINAL
# --------------------------------------------------------------------------

def formatar_cnpj(basico: str, ordem: str, dv: str) -> str:
    n = f"{basico}{ordem}{dv}"
    n = n.zfill(14)
    return f"{n[0:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:14]}"


def montar_csv_final(
    linhas_estabelecimento: List[List[str]],
    razoes_sociais: Dict[str, Tuple[str, str, str]],
    tabela_municipios: Dict[str, str],
    tabela_cnaes: Dict[str, str],
) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        escritor = csv.writer(f)
        escritor.writerow([
            "cnpj", "razao_social", "nome_fantasia", "cnae_principal",
            "descricao_cnae", "situacao_cadastral", "logradouro", "numero",
            "complemento", "bairro", "cep", "municipio", "uf",
            "ddd_telefone", "email", "capital_social", "porte_empresa",
        ])
        for linha in linhas_estabelecimento:
            cnpj_basico = linha[IDX_CNPJ_BASICO].strip()
            cnpj_fmt = formatar_cnpj(
                cnpj_basico, linha[IDX_CNPJ_ORDEM].strip(), linha[IDX_CNPJ_DV].strip()
            )
            razao_social, capital_social, porte = razoes_sociais.get(
                cnpj_basico, ("", "", "")
            )
            cnae_cod = linha[IDX_CNAE_PRINCIPAL].strip()
            descricao_cnae = tabela_cnaes.get(cnae_cod, "")
            municipio_cod = linha[IDX_MUNICIPIO_COD].strip()
            municipio_nome = tabela_municipios.get(municipio_cod, municipio_cod)
            telefone = ""
            if linha[IDX_DDD1].strip() or linha[IDX_TEL1].strip():
                telefone = f"({linha[IDX_DDD1].strip()}) {linha[IDX_TEL1].strip()}"

            escritor.writerow([
                cnpj_fmt,
                razao_social,
                linha[IDX_NOME_FANTASIA].strip(),
                cnae_cod,
                descricao_cnae,
                linha[IDX_SITUACAO_CADASTRAL].strip(),
                f"{linha[IDX_LOGRADOURO_TIPO].strip()} {linha[IDX_LOGRADOURO].strip()}".strip(),
                linha[IDX_NUMERO].strip(),
                linha[IDX_COMPLEMENTO].strip(),
                linha[IDX_BAIRRO].strip(),
                linha[IDX_CEP].strip(),
                municipio_nome,
                linha[IDX_UF].strip(),
                telefone,
                linha[IDX_EMAIL].strip(),
                capital_social,
                porte,
            ])
    print(f"\n[OK] Arquivo final salvo em: {OUTPUT_FILE}")
    print(f"[OK] Total de estabelecimentos exportados: {len(linhas_estabelecimento)}")


# --------------------------------------------------------------------------
# BUSCAR CÓDIGO DO MUNICÍPIO A PARTIR DO NOME (a RFB usa código próprio,
# diferente do código IBGE)
# --------------------------------------------------------------------------

def encontrar_codigo_municipio(tabela_municipios: Dict[str, str], nome_municipio: str) -> Optional[str]:
    nome_upper = nome_municipio.strip().upper()
    for codigo, nome in tabela_municipios.items():
        if nome.strip().upper() == nome_upper:
            return codigo
    # Tenta correspondência parcial se não achar exata
    candidatos = [c for c, n in tabela_municipios.items() if nome_upper in n.strip().upper()]
    if len(candidatos) == 1:
        return candidatos[0]
    if len(candidatos) > 1:
        print(f"[AVISO] Mais de um município bateu com '{nome_municipio}': "
              f"{[tabela_municipios[c] for c in candidatos]}. Nenhum filtro de município será aplicado.")
    return None


# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Baixa e filtra a base de Dados Abertos de CNPJ da Receita Federal por CNAE de imobiliárias."
    )
    parser.add_argument(
        "--municipio", type=str, default=None,
        help='Nome do município para filtrar (ex: "IPATINGA"). Se omitido, traz o Brasil inteiro (arquivo grande).'
    )
    parser.add_argument(
        "--cnae", action="append", default=None,
        help="Código de CNAE (7 dígitos, sem pontuação) a incluir no filtro. Pode repetir a flag várias vezes. "
             "Se omitido, usa a lista padrão de CNAEs imobiliários."
    )
    parser.add_argument(
        "--incluir-inativas", action="store_true",
        help="Por padrão só empresas ATIVAS são incluídas. Use esta flag para incluir baixadas/suspensas também."
    )
    args = parser.parse_args()

    cnaes_alvo = set(args.cnae) if args.cnae else set(DEFAULT_TARGET_CNAES)
    apenas_ativas = not args.incluir_inativas

    os.makedirs(WORKDIR, exist_ok=True)

    pasta_url = descobrir_pasta_mais_recente()
    arquivos_disponiveis = listar_arquivos_da_pasta(pasta_url)
    print(f"[INFO] {len(arquivos_disponiveis)} arquivo(s) .zip disponíveis nesta pasta.")

    tabela_cnaes = carregar_tabela_apoio(pasta_url, arquivos_disponiveis, "CNAES")
    tabela_municipios = carregar_tabela_apoio(pasta_url, arquivos_disponiveis, "MUNICIPIOS")

    codigo_municipio_alvo = None
    if args.municipio:
        codigo_municipio_alvo = encontrar_codigo_municipio(tabela_municipios, args.municipio)
        if codigo_municipio_alvo:
            print(f"[INFO] Município '{args.municipio}' -> código RFB {codigo_municipio_alvo}")
        else:
            print(f"[AVISO] Município '{args.municipio}' não encontrado na tabela. "
                  f"Prosseguindo sem filtro de município.")

    print(f"[INFO] CNAEs alvo: {sorted(cnaes_alvo)}")

    linhas_filtradas = processar_estabelecimentos(
        pasta_url, arquivos_disponiveis, cnaes_alvo, codigo_municipio_alvo, apenas_ativas
    )

    if not linhas_filtradas:
        print("[INFO] Nenhum estabelecimento encontrado com os filtros atuais. Encerrando.")
        return

    cnpjs_basicos_necessarios = {linha[IDX_CNPJ_BASICO].strip() for linha in linhas_filtradas}
    razoes_sociais = buscar_razao_social(pasta_url, arquivos_disponiveis, cnpjs_basicos_necessarios)

    montar_csv_final(linhas_filtradas, razoes_sociais, tabela_municipios, tabela_cnaes)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INTERROMPIDO PELO USUÁRIO]")
        sys.exit(1)
