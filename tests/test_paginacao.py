import unittest

from paginacao import paginas_visiveis


class PaginacaoTest(unittest.TestCase):
    def test_mostra_todas_as_paginas_quando_sao_poucas(self):
        self.assertEqual(paginas_visiveis(3, 7), [1, 2, 3, 4, 5, 6, 7])

    def test_compacta_no_inicio(self):
        self.assertEqual(paginas_visiveis(1, 30), [1, 2, 3, 4, 5, None, 30])

    def test_compacta_no_meio(self):
        self.assertEqual(paginas_visiveis(15, 30), [1, None, 14, 15, 16, None, 30])

    def test_compacta_no_fim(self):
        self.assertEqual(paginas_visiveis(30, 30), [1, None, 26, 27, 28, 29, 30])

    def test_limita_pagina_fora_do_intervalo(self):
        self.assertEqual(paginas_visiveis(99, 3), [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
