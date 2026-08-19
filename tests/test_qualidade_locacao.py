import unittest

from qualidade_locacao import revisar_anuncio_locacao


class QualidadeLocacaoTests(unittest.TestCase):
    def test_rejeita_venda_sem_locacao(self):
        decisao = revisar_anuncio_locacao(
            "Casa à venda", "https://exemplo.test/casa-a-venda", 750000
        )
        self.assertFalse(decisao["publicar"])

    def test_oferta_mista_sem_periodo_mensal_fica_sob_consulta(self):
        decisao = revisar_anuncio_locacao(
            "Casa à venda ou aluguel", "https://exemplo.test/casa", 750000,
            contexto_preco="R$ 750.000",
        )
        self.assertTrue(decisao["publicar"])
        self.assertIsNone(decisao["preco"])

    def test_valor_mensal_misto_e_aceito(self):
        decisao = revisar_anuncio_locacao(
            "Casa à venda ou aluguel", "https://exemplo.test/casa", 2500,
            contexto_preco="Aluguel R$ 2.500/mês",
        )
        self.assertEqual(decisao["preco"], 2500.0)

    def test_milhar_com_virgula_permanece_valido(self):
        decisao = revisar_anuncio_locacao(
            "Apartamento para alugar", "https://exemplo.test/apto", 1000,
            contexto_preco="R$ 1,000 por mês",
        )
        self.assertEqual(decisao["preco"], 1000.0)

    def test_preco_antigo_baixo_fica_sob_consulta(self):
        decisao = revisar_anuncio_locacao(
            "Apartamento para alugar", "https://exemplo.test/apto", 1.0,
            contexto_preco="R$ 1,00/mês",
        )
        self.assertIsNone(decisao["preco"])


if __name__ == "__main__":
    unittest.main()
