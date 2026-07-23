import unittest

from descobrir_sites import (
    avaliar_pagina_imobiliaria,
    dominio,
    pontuar,
    url_canonica,
)
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

    def test_portais_nacionais_sao_excluidos(self):
        self.assertLess(
            pontuar(
                "https://www.vivareal.com.br/aluguel/minas-gerais/ipatinga/",
                "Imóveis para alugar",
                municipio="Ipatinga",
            ),
            0,
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
