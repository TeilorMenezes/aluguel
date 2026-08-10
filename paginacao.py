"""Funcoes puras usadas pela paginacao dos resultados."""


def paginas_visiveis(pagina_atual: int, total_paginas: int) -> list[int | None]:
    """Retorna uma paginacao compacta; ``None`` representa reticencias."""
    total_paginas = max(1, int(total_paginas))
    pagina_atual = min(max(1, int(pagina_atual)), total_paginas)

    if total_paginas <= 7:
        return list(range(1, total_paginas + 1))

    if pagina_atual <= 4:
        paginas = {1, 2, 3, 4, 5, total_paginas}
    elif pagina_atual >= total_paginas - 3:
        paginas = {1, *range(total_paginas - 4, total_paginas + 1)}
    else:
        paginas = {1, pagina_atual - 1, pagina_atual, pagina_atual + 1, total_paginas}

    resultado: list[int | None] = []
    anterior = 0
    for pagina in sorted(paginas):
        if pagina - anterior > 1:
            resultado.append(None)
        resultado.append(pagina)
        anterior = pagina
    return resultado
