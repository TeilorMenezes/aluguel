import tempfile
import unittest
from pathlib import Path

import db
from filtros_publicos import parametros_resultados_url, restaurar_filtros_resultados


class FiltrosPublicosTest(unittest.TestCase):
    def test_restaura_url_compativel_e_descarta_parametros_invalidos(self):
        filtros = restaurar_filtros_resultados(
            {
                "cidade": "Ipatinga",
                "bairro": ["Centro", "Inválido", "Centro"],
                "categoria": "Apartamento",
                "imobiliaria": ["Alfa", "Fora"],
                "preco_min": "1200,50",
                "preco_max": "2000",
                "sob_consulta": "0",
                "ordem": "preco_asc",
                "pagina": "3",
            },
            cidades=["Ipatinga"],
            bairros=["Centro"],
            tipos=["Todos os tipos", "Apartamento"],
            imobiliarias=["Alfa"],
            preco_minimo=500,
            preco_maximo=5000,
            todas_cidades="Todas as cidades",
            todos_tipos="Todos os tipos",
        )

        self.assertEqual("Ipatinga", filtros["cidade"])
        self.assertEqual(["Centro"], filtros["bairros"])
        self.assertEqual("Apartamento", filtros["tipo"])
        self.assertEqual(["Alfa"], filtros["imobiliarias"])
        self.assertEqual(1200.5, filtros["preco_min"])
        self.assertEqual(2000.0, filtros["preco_max"])
        self.assertFalse(filtros["incluir_sem_preco"])
        self.assertEqual("preco_asc", filtros["ordem"])
        self.assertEqual(3, filtros["pagina"])

    def test_parametros_invalidos_voltam_para_estado_seguro(self):
        filtros = restaurar_filtros_resultados(
            {
                "cidade": "Cidade inexistente",
                "tipo": "Tipo inventado",
                "preco_min": "4000",
                "preco_max": "1000",
                "sob_consulta": "talvez",
                "ordem": "aleatoria",
                "pagina": "zero",
            },
            cidades=["Ipatinga"],
            bairros=[],
            tipos=["Todos os tipos"],
            imobiliarias=[],
            preco_minimo=500,
            preco_maximo=5000,
            todas_cidades="Todas as cidades",
            todos_tipos="Todos os tipos",
        )

        self.assertEqual("Todas as cidades", filtros["cidade"])
        self.assertEqual("Todos os tipos", filtros["tipo"])
        self.assertIsNone(filtros["preco_min"])
        self.assertIsNone(filtros["preco_max"])
        self.assertTrue(filtros["incluir_sem_preco"])
        self.assertEqual("recentes", filtros["ordem"])
        self.assertEqual(1, filtros["pagina"])

    def test_serializa_listas_e_omite_valores_padrao(self):
        parametros = parametros_resultados_url(
            {
                "cidade": "Todas as cidades",
                "bairros": ["Centro"],
                "tipo": "Todos os tipos",
                "imobiliarias": ["Alfa"],
                "preco_min": None,
                "preco_max": 2200.0,
                "incluir_sem_preco": True,
                "ordem": "recentes",
                "pagina": 2,
            },
            todas_cidades="Todas as cidades",
            todos_tipos="Todos os tipos",
        )

        self.assertEqual(
            {
                "tela": "resultados",
                "bairro": ["Centro"],
                "imobiliaria": ["Alfa"],
                "preco_max": "2200.0",
                "sob_consulta": "1",
                "ordem": "recentes",
                "pagina": "2",
            },
            parametros,
        )


class ConsultasPublicasTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path_original = db.DB_PATH
        db.DB_PATH = Path(self.temp_dir.name) / "imoveis.db"
        db.init_public_db()
        self._inserir("/a", 1000, "2026-08-10T10:00:00-03:00")
        self._inserir("/b", 1000, "2026-08-10T10:00:00-03:00")
        self._inserir("/c", 2000, "2026-08-11T10:00:00-03:00")
        self._inserir("/consulta", None, "2026-08-11T10:00:00-03:00")

    def tearDown(self):
        db.DB_PATH = self.db_path_original
        self.temp_dir.cleanup()

    @staticmethod
    def _item(url, preco, coletado_em):
        return {
            "site_key": "teste",
            "imobiliaria": "Alfa",
            "logo_url": None,
            "url": f"https://exemplo.test{url}",
            "titulo": "Imóvel teste",
            "tipo": "Apartamento",
            "preco": preco,
            "bairro": "Centro",
            "cidade": "Ipatinga",
            "thumbnail_url": None,
            "latitude": None,
            "longitude": None,
            "coletado_em": coletado_em,
        }

    def _inserir(self, url, preco, coletado_em):
        db.upsert_imovel(self._item(url, preco, coletado_em))

    def test_contagem_e_listagem_compartilham_filtros_e_sob_consulta(self):
        filtros = {"preco_min": 900, "preco_max": 1500, "incluir_sem_preco": True}
        self.assertEqual(3, db.contar_imoveis(**filtros))
        self.assertEqual(3, len(db.listar_imoveis(**filtros)))

    def test_ordenacoes_tem_desempate_estavel(self):
        recentes = db.listar_imoveis(ordenar_por="recentes")
        crescentes = db.listar_imoveis(ordenar_por="preco_asc")
        decrescentes = db.listar_imoveis(ordenar_por="preco_desc")

        self.assertEqual("https://exemplo.test/consulta", recentes[0]["url"])
        self.assertEqual(
            ["https://exemplo.test/b", "https://exemplo.test/a"],
            [item["url"] for item in crescentes[:2]],
        )
        self.assertEqual("https://exemplo.test/c", decrescentes[0]["url"])


if __name__ == "__main__":
    unittest.main()
