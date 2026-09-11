import unittest
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import urlparse

import yaml

import scraper


ROOT = Path(__file__).resolve().parents[1]

ACTIVE_SOURCES = {
    "total_imobiliaria",
    "carneiro_imoveis",
    "porta_aberta_imoveis",
    "jhessica_marcelo_imoveis",
    "unicom_imoveis",
    "druwe_imoveis",
    "vasconcelos_imoveis",
    "solucao_imobiliaria",
    "seguranca_imoveis",
    "lins_imoveis",
    "bom_negocio_gv",
    "imoveis_carvalho",
    "geferson_gomes_imoveis",
    "guerrinha_imoveis",
    "predileta_imoveis",
    "betel_imoveis",
}


class _ImageElement:
    def __init__(self, attributes=None):
        self.attributes = attributes or {}

    def get_attribute(self, name):
        return self.attributes.get(name)

    def query_selector(self, _selector):
        return None


class FontesValeGvTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = yaml.safe_load((ROOT / "sites_config.yaml").read_text(encoding="utf-8"))
        cls.sites = config["sites"]

    def test_fontes_ativadas_tem_origem_oficial_e_finalidade_aluguel(self):
        self.assertTrue(ACTIVE_SOURCES.issubset(self.sites))
        for site_key in ACTIVE_SOURCES:
            with self.subTest(site=site_key):
                site = self.sites[site_key]
                self.assertNotEqual(site.get("coleta_ativa"), False)
                self.assertEqual(site.get("finalidade"), "aluguel")
                base_host = (urlparse(site["base_url"]).hostname or "").removeprefix("www.")
                listing_host = (urlparse(site["listagem_url"]).hostname or "").removeprefix("www.")
                self.assertEqual(base_host, listing_host)
                self.assertNotIn(base_host, {"zapimoveis.com.br", "vivareal.com.br", "olx.com.br"})

    def test_paginacao_ativa_tem_limite_e_criterio_deterministico(self):
        for site_key in ACTIVE_SOURCES:
            with self.subTest(site=site_key):
                site = self.sites[site_key]
                pagination = site.get("paginacao", {})
                self.assertIn(pagination.get("tipo"), {"nenhuma", "url", "api"})
                if pagination.get("tipo") in {"url", "api"}:
                    self.assertGreater(pagination.get("max_paginas", 0), 0)
                if pagination.get("tipo") == "url":
                    template = pagination.get("url_template")
                    if template:
                        self.assertIn("{pagina}", template)
                    else:
                        listing_url = site["listagem_url"]
                        self.assertTrue(
                            "{pagina}" in listing_url or listing_url.endswith("/")
                        )

    def test_listagens_mistas_exigem_link_de_locacao(self):
        for site_key in {
            "total_imobiliaria",
            "carneiro_imoveis",
            "porta_aberta_imoveis",
            "jhessica_marcelo_imoveis",
        }:
            with self.subTest(site=site_key):
                site = self.sites[site_key]
                self.assertTrue(site["link_obrigatorio"])
                self.assertIn("/imoveis/locacao-", site["seletores"]["link"])
                self.assertIn("status", site["seletores"])

    def test_api_publica_da_betel_e_preferida_ao_navegador(self):
        site = self.sites["betel_imoveis"]
        self.assertEqual(site["integracao"], "imoview_api")
        self.assertEqual(site["paginacao"]["tipo"], "api")
        self.assertEqual(
            urlparse(site["api_url"]).hostname,
            urlparse(site["base_url"]).hostname,
        )

    def test_fontes_com_baixa_cobertura_ficam_em_quarentena(self):
        expected = {
            "glaucia_veras": "18%",
            "tataia_imoveis": "0%",
        }
        for site_key, evidence in expected.items():
            with self.subTest(site=site_key):
                site = self.sites[site_key]
                self.assertFalse(site["coleta_ativa"])
                self.assertIn(evidence, site["motivo_quarentena"])

    def test_link_obrigatorio_nao_recua_para_venda(self):
        fallback = MagicMock()
        fallback.get_attribute.return_value = "/imoveis/venda-casa"
        card = MagicMock()
        card.query_selector.return_value = None
        card.query_selector_all.return_value = [fallback]

        self.assertIsNone(
            scraper._link_do_imovel(card, "a[href*='/locacao-']", exigir_preferido=True)
        )
        self.assertIs(
            scraper._link_do_imovel(card, "a[href*='/locacao-']"),
            fallback,
        )

    def test_placeholder_nao_e_publicado_como_foto(self):
        self.assertIsNone(
            scraper._url_imagem_elemento(
                _ImageElement({"src": "/images/image-not-found.jpg"})
            )
        )
        self.assertIsNone(
            scraper._url_imagem_elemento(
                _ImageElement({"src": "https://via.placeholder.com/488x326"})
            )
        )
        self.assertFalse(
            scraper._eh_placeholder_imagem("https://notplaceholder.com/foto.jpg")
        )

    def test_buscar_nao_e_inferido_como_cidade(self):
        self.assertIsNone(
            scraper._cidade_da_url("https://exemplo.test/buscar?availability=rent")
        )


if __name__ == "__main__":
    unittest.main()
