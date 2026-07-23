import unittest

from descobrir_sites import (
    _coletar_links_busca,
    avaliar_pagina_imobiliaria,
    dominio,
    pontuar,
    url_canonica,
)
from bs4 import BeautifulSoup
from detector import avaliar_extracao, detectar_seletores


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
