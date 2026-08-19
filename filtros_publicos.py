"""Funções puras para o estado dos filtros do catálogo público."""

from collections.abc import Mapping


ORDENS_RESULTADOS = ("recentes", "preco_asc", "preco_desc")


def valores_parametro(parametros: Mapping[str, object], nome: str) -> list[str]:
    """Lê um parâmetro simples ou repetido sem depender do Streamlit."""
    valor = parametros.get(nome)
    if valor is None:
        return []
    if isinstance(valor, (list, tuple)):
        return [str(item) for item in valor]
    return [str(valor)]


def primeiro_parametro(parametros: Mapping[str, object], nome: str) -> str | None:
    valores = valores_parametro(parametros, nome)
    return valores[-1] if valores else None


def selecoes_validas(selecoes: list[str], opcoes: list[str]) -> list[str]:
    """Mantém somente opções ainda disponíveis, sem duplicá-las."""
    permitidas = set(opcoes)
    resultado = []
    for selecao in selecoes:
        if selecao in permitidas and selecao not in resultado:
            resultado.append(selecao)
    return resultado


def numero_no_intervalo(valor: str | None, minimo: float, maximo: float) -> float | None:
    if valor in (None, ""):
        return None
    try:
        numero = float(valor.replace(",", "."))
    except (AttributeError, ValueError):
        return None
    return numero if minimo <= numero <= maximo else None


def booleano_parametro(valor: str | None, padrao: bool) -> bool:
    if valor is None:
        return padrao
    if valor.lower() in {"1", "true", "sim", "yes"}:
        return True
    if valor.lower() in {"0", "false", "nao", "não", "no"}:
        return False
    return padrao


def pagina_valida(valor: str | None) -> int:
    try:
        return max(1, int(valor or "1"))
    except ValueError:
        return 1


def restaurar_filtros_resultados(
    parametros: Mapping[str, object],
    *,
    cidades: list[str],
    bairros: list[str],
    tipos: list[str],
    imobiliarias: list[str],
    preco_minimo: float,
    preco_maximo: float,
    todas_cidades: str,
    todos_tipos: str,
) -> dict[str, object]:
    """Converte a URL em um estado seguro, descartando valores inválidos."""
    cidades_selecionadas = selecoes_validas(valores_parametro(parametros, "cidade"), cidades)
    cidade = cidades_selecionadas[0] if len(cidades_selecionadas) == 1 else todas_cidades

    tipo = primeiro_parametro(parametros, "tipo") or primeiro_parametro(parametros, "categoria")
    tipo = tipo if tipo in tipos else todos_tipos

    preco_min = numero_no_intervalo(
        primeiro_parametro(parametros, "preco_min"), preco_minimo, preco_maximo
    )
    preco_max = numero_no_intervalo(
        primeiro_parametro(parametros, "preco_max"), preco_minimo, preco_maximo
    )
    if preco_min is not None and preco_max is not None and preco_min > preco_max:
        preco_min, preco_max = None, None

    ordem = primeiro_parametro(parametros, "ordem")
    return {
        # "cidade" continua disponível para links e integrações antigos.
        "cidade": cidade,
        "cidades": cidades_selecionadas,
        "bairros": selecoes_validas(valores_parametro(parametros, "bairro"), bairros),
        "tipo": tipo,
        "imobiliarias": selecoes_validas(
            valores_parametro(parametros, "imobiliaria"), imobiliarias
        ),
        "preco_min": preco_min,
        "preco_max": preco_max,
        "incluir_sem_preco": booleano_parametro(
            primeiro_parametro(parametros, "sob_consulta"), True
        ),
        "ordem": ordem if ordem in ORDENS_RESULTADOS else "recentes",
        "pagina": pagina_valida(primeiro_parametro(parametros, "pagina")),
    }


def parametros_resultados_url(
    filtros: Mapping[str, object], *, todas_cidades: str, todos_tipos: str
) -> dict[str, str | list[str]]:
    """Serializa o estado canônico dos filtros para a URL pública."""
    parametros: dict[str, str | list[str]] = {"tela": "resultados"}
    cidades = filtros.get("cidades")
    cidade_legada = filtros.get("cidade", todas_cidades)
    if not cidades and cidade_legada != todas_cidades:
        cidades = [str(cidade_legada)]
    if cidades:
        parametros["cidade"] = list(dict.fromkeys(str(cidade) for cidade in cidades))
    if filtros["tipo"] != todos_tipos:
        parametros["tipo"] = str(filtros["tipo"])
    if filtros["bairros"]:
        parametros["bairro"] = list(filtros["bairros"])
    if filtros["imobiliarias"]:
        parametros["imobiliaria"] = list(filtros["imobiliarias"])
    if filtros["preco_min"] is not None:
        parametros["preco_min"] = str(filtros["preco_min"])
    if filtros["preco_max"] is not None:
        parametros["preco_max"] = str(filtros["preco_max"])
    parametros["sob_consulta"] = "1" if filtros["incluir_sem_preco"] else "0"
    parametros["ordem"] = str(filtros["ordem"])
    parametros["pagina"] = str(filtros["pagina"])
    return parametros
