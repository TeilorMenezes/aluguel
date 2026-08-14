import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from descobrir_sites import (
    _coletar_links_busca,
    avaliar_pagina_imobiliaria,
    dominio,
    listar_quarentena,
    pontuar,
    registrar_quarentena,
    remover_da_quarentena,
    url_canonica,
)
from bs4 import BeautifulSoup
from detector import avaliar_extracao, detectar_seletores
from detector_ai import _validate_choice, build_candidate_packet, suggest_selectors


def html_listagem(finalidade="aluguel", quantidade=6):
    cards = []
    for numero in range(1, quantidade + 1):
        cards.append(
            f"""
            <article class="property-card">
              <a class="property-link" href="/imovel/{numero}">
                <img class="property-photo" data-src="/foto-{numero}.jpg">
                <h2 class="property-title">Apartamento para {finalidade} no Centro</h2>
                <span class="property-price">R$ {numero}.200,00</span>
                <span class="property-address">Centro - Ipatinga</span>
              </a>
            </article>
            """
        )
    return (
        "<html><head><title>Exemplo Imobiliária</title></head>"
        f"<body><h1>Imóveis para {finalidade} em Ipatinga</h1>"
        + "".join(cards)
        + "</body></html>"
    )


class DescobertaSitesTest(unittest.TestCase):
    def test_detector_tolera_classes_de_layout_variaveis(self):
        html = "<main>" + "".join(
            f'''<article class="property-card col-{index} flex">
              <a class="detail-link" href="/imovel/{index}"><span class="name">Apartamento Centro {index}</span></a>
              <span class="price">R$ {1200 + index * 100}</span>
              <figure class="photo" style="background-image:url('/foto-{index}.webp')"></figure>
            </article>'''
            for index in range(1, 6)
        ) + "<p>Imóveis para aluguel e locação</p></main>"
        detected = detectar_seletores(html)
        self.assertEqual(detected["seletores"]["card"], "article.property-card")
        self.assertEqual(detected["seletores"]["preco"], "span.price")
        self.assertEqual(detected["seletores"]["thumbnail"], "figure.photo")
        validation = avaliar_extracao(
            html, detected["seletores"], "https://exemplo.test/aluguel"
        )
        self.assertGreaterEqual(validation["taxas_campos"]["thumbnail"], 0.9)

    def test_detector_prefere_imovelcard_a_container_generico(self):
        blocks = []
        for index in range(4):
            blocks.append(f'''<section class="container">
              <div class="imovelcard"><a href="/imovel/{index}">
                <h2 class="imovelcard__titulo">Casa no Centro {index}</h2>
                <div class="imovelcard__valor">R$ 2.{index}00</div>
                <img src="/foto-{index}.jpg"></a></div>
            </section>''')
        detected = detectar_seletores(
            "<main>" + "".join(blocks) + "<p>Aluguel locação</p></main>"
        )
        self.assertEqual(detected["seletores"]["card"], "div.imovelcard")
        self.assertEqual(detected["seletores"]["preco"], "div.imovelcard__valor")

    def test_pacote_de_ia_so_aceita_ids_pre_gerados(self):
        html = "".join(
            f'<article class="card"><a class="link" href="/imovel/{i}">Casa {i}</a><b class="preco">R$ 1.500</b></article>'
            for i in range(4)
        )
        packet = build_candidate_packet(html, "https://exemplo.test/aluguel")
        by_selector = {item["selector"]: item["id"] for item in packet["candidates"]}
        choice = {"candidate_ids": {
            "card": by_selector["article.card"], "link": by_selector["a.link"],
            "preco": by_selector["b.preco"], "titulo": by_selector["a.link"],
            "thumbnail": None, "bairro": None, "tipo": None,
        }}
        self.assertEqual(_validate_choice(choice, packet)["card"], "article.card")
        choice["candidate_ids"]["card"] = "inventado"
        with self.assertRaises(ValueError):
            _validate_choice(choice, packet)

    def test_normaliza_dominio_e_remove_rastreamento(self):
        self.assertEqual(dominio("https://www.Exemplo.com.br/x"), "exemplo.com.br")
        self.assertEqual(
            url_canonica("https://exemplo.com.br/aluguel?pagina=2&utm_source=x#topo"),
            "https://exemplo.com.br/aluguel?pagina=2",
        )

    def test_extrai_destino_de_redirecionamento_yahoo(self):
        from descobrir_sites import url_resultado

        redirecionamento = (
            "https://r.search.yahoo.com/x/RU=https%3A%2F%2F"
            "exemplo.com.br%2Faluguel/RK=2/RS=abc"
        )
        self.assertEqual(
            url_resultado(redirecionamento),
            "https://exemplo.com.br/aluguel",
        )

    def test_portais_nacionais_sao_excluidos(self):
        self.assertLess(
            pontuar(
                "https://www.vivareal.com.br/aluguel/minas-gerais/ipatinga/",
                "Imóveis para alugar",
                municipio="Ipatinga",
            ),
            0,
        )

    def test_extrai_resultados_da_busca_e_remove_portais(self):
        soup = BeautifulSoup(
            """
            <div class="snippet">
              <a href="https://exemploimoveis.com.br/aluguel">
                Exemplo Imóveis em Ipatinga
              </a>
            </div>
            <div class="snippet">
              <a href="https://www.vivareal.com.br/aluguel/ipatinga/">
                Portal nacional
              </a>
            </div>
            """,
            "html.parser",
        )
        resultados = _coletar_links_busca(
            soup,
            ("div.snippet a[href]",),
            limite=10,
        )
        self.assertEqual(
            resultados,
            [
                (
                    "https://exemploimoveis.com.br/aluguel",
                    "Exemplo Imóveis em Ipatinga",
                )
            ],
        )

    def test_quarentena_pode_ser_listada_atualizada_e_removida(self):
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "quarentena.csv"
            registrar_quarentena(
                [{
                    "dominio": "exemplo.com.br",
                    "nome": "Exemplo Imóveis",
                    "municipio": "Ipatinga",
                    "url": "https://exemplo.com.br/aluguel",
                    "score": 55,
                    "motivo": "Preço não identificado.",
                    "evidencias": ["listagem de aluguel"],
                }],
                caminho,
            )
            linhas = listar_quarentena(caminho)
            self.assertEqual(len(linhas), 1)
            self.assertEqual(linhas[0]["municipio"], "Ipatinga")

            registrar_quarentena(
                [{
                    **linhas[0],
                    "score": 70,
                    "motivo": "Pronto para aprovação manual.",
                    "evidencias": ["preço identificado"],
                }],
                caminho,
            )
            atualizada = listar_quarentena(caminho)
            self.assertEqual(atualizada[0]["motivo"], "Pronto para aprovação manual.")

            remover_da_quarentena("https://www.exemplo.com.br/x", caminho)
            self.assertEqual(listar_quarentena(caminho), [])

    def test_site_local_recebe_sinais_positivos(self):
        score = pontuar(
            "https://exemploimoveis.com.br/imoveis/para-alugar",
            "Exemplo Imóveis | Aluguel em Ipatinga",
            nome="Exemplo Imóveis",
            municipio="Ipatinga",
        )
        self.assertGreaterEqual(score, 45)

    def test_avaliacao_reconhece_listagem_de_aluguel(self):
        resultado = avaliar_pagina_imobiliaria(
            "https://exemplo.com.br/imoveis/para-alugar",
            html_listagem(),
            municipio="Ipatinga",
            nome="Exemplo Imóveis",
        )
        self.assertGreaterEqual(resultado["score_pagina"], 65)
        self.assertIn("URL específica de aluguel", resultado["evidencias"])
        self.assertGreaterEqual(resultado["links_imoveis"], 3)

    def test_detector_valida_dados_reais_dos_cards(self):
        html = html_listagem()
        deteccao = detectar_seletores(html)
        self.assertNotIn("erro", deteccao)
        self.assertEqual(deteccao["seletores"]["card"], "article.property-card")
        validacao = avaliar_extracao(
            html,
            deteccao["seletores"],
            "https://exemplo.com.br/aluguel",
        )
        self.assertTrue(validacao["publicavel"])
        self.assertGreaterEqual(validacao["taxas_campos"]["link"], 0.9)
        self.assertGreaterEqual(validacao["taxas_campos"]["preco"], 0.9)

    def test_detector_nao_confunde_quartos_com_preco(self):
        html = """
        <section>
          <article class="imovelcard">
            <a class="foto" href="/imovel/1"><img src="/1.jpg"></a>
            <h2 class="status">Locação</h2>
            <div class="feature">2 Dormitórios</div>
            <p class="valor">R$ 1.200</p>
          </article>
          <article class="imovelcard">
            <a class="foto" href="/imovel/2"><img src="/2.jpg"></a>
            <h2 class="status">Locação</h2>
            <div class="feature">3 Dormitórios</div>
            <p class="valor">R$ 1.800</p>
          </article>
          <article class="imovelcard">
            <a class="foto" href="/imovel/3"><img src="/3.jpg"></a>
            <h2 class="status">Locação</h2>
            <div class="feature">1 Dormitório</div>
            <p class="valor">R$ 900</p>
          </article>
        </section>
        """
        resultado = detectar_seletores(html)
        self.assertEqual(resultado["seletores"]["preco"], "p.valor")
        self.assertEqual(resultado["seletores"]["thumbnail"], "img")

    def test_estoque_pequeno_com_dois_anuncios_validos_e_publicavel(self):
        html = """
        <main>
          <article class="card">
            <a class="link" href="/imovel/1">
              <img src="/1.jpg"><h2>Apartamento para locação</h2>
            </a>
            <p class="preco">R$ 1.200</p>
          </article>
          <article class="card">
            <a class="link" href="/imovel/2">
              <img src="/2.jpg"><h2>Casa para locação</h2>
            </a>
            <p class="preco">R$ 1.800</p>
          </article>
          <article class="card"><p>Consulte outros imóveis</p></article>
        </main>
        """
        validacao = avaliar_extracao(
            html,
            {
                "card": "article.card",
                "link": "a.link",
                "titulo": "h2",
                "preco": "p.preco",
                "thumbnail": "img",
            },
            "https://exemplo.com.br/locacao",
        )
        self.assertTrue(validacao["publicavel"])
        self.assertEqual(validacao["taxas_campos"]["links_unicos"], 2)

    def test_imagem_nao_compensa_titulo_ausente(self):
        html = "<p>Aluguel locação</p>" + "".join(
            f'<article class="card"><a href="/imovel/{i}"></a><p class="preco">R$ 1.500</p><img src="/{i}.jpg"></article>'
            for i in range(4)
        )
        result = avaliar_extracao(html, {
            "card": "article.card", "link": "a", "titulo": "h2",
            "preco": "p.preco", "thumbnail": "img",
        }, "https://exemplo.test/aluguel")
        self.assertFalse(result["publicavel"])

    def test_area_em_metros_quadrados_nao_e_validada_como_preco(self):
        html = "<p>Aluguel locação</p>" + "".join(
            f'<article class="card"><a href="/imovel/{i}"><h2>Casa {i}</h2></a>'
            f'<p class="area">1.200 m²</p><img src="/{i}.jpg"></article>'
            for i in range(4)
        )
        result = avaliar_extracao(html, {
            "card": "article.card", "link": "a", "titulo": "h2",
            "preco": "p.area", "thumbnail": "img",
        }, "https://exemplo.test/aluguel")
        self.assertEqual(result["taxas_campos"]["preco"], 0)
        self.assertFalse(result["publicavel"])

    def test_link_externo_de_compartilhamento_nao_e_validado_como_imovel(self):
        html = "<p>Aluguel locação</p>" + "".join(
            f'<article class="card"><a href="https://social.example/share/{i}"><h2>Casa {i}</h2></a>'
            f'<p class="preco">R$ 1.200</p><img src="/{i}.jpg"></article>'
            for i in range(4)
        )
        result = avaliar_extracao(html, {
            "card": "article.card", "link": "a", "titulo": "h2",
            "preco": "p.preco", "thumbnail": "img",
        }, "https://exemplo.test/aluguel")
        self.assertEqual(result["taxas_campos"]["link"], 0)
        self.assertFalse(result["publicavel"])

    def test_modo_ia_local_recusa_endpoint_remoto(self):
        with patch.dict("os.environ", {
            "IMOVEIS_AI_SELECTOR_MODE": "local",
            "IMOVEIS_AI_SELECTOR_ENDPOINT": "https://ia.example/api",
        }, clear=False):
            with self.assertRaises(ValueError):
                suggest_selectors(html_listagem(), "https://exemplo.test/aluguel")

    def test_pagina_exclusiva_de_venda_nao_e_publicavel(self):
        html = html_listagem(finalidade="venda")
        deteccao = detectar_seletores(html)
        validacao = avaliar_extracao(
            html,
            deteccao["seletores"],
            "https://exemplo.com.br/imoveis-a-venda",
        )
        self.assertFalse(validacao["eh_listagem_aluguel"])
        self.assertFalse(validacao["publicavel"])


if __name__ == "__main__":
    unittest.main()
