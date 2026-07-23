import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import db
import scraper


class RoboLocalTest(unittest.TestCase):
    def test_status_por_site_e_persistente(self):
        with TemporaryDirectory() as pasta:
            banco = Path(pasta) / "teste.db"
            with patch.object(db, "DB_PATH", banco):
                db.init_db()
                db.registrar_status_site(
                    "exemplo",
                    "executando",
                    tentativas=1,
                )
                db.registrar_status_site(
                    "exemplo",
                    "concluido",
                    tentativas=2,
                    imoveis_coletados=7,
                )
                status = db.listar_status_sites()

        self.assertEqual(len(status), 1)
        self.assertEqual(status[0]["site_key"], "exemplo")
        self.assertEqual(status[0]["status"], "concluido")
        self.assertEqual(status[0]["tentativas"], 2)
        self.assertEqual(status[0]["imoveis_coletados"], 7)

    def test_site_faz_tres_tentativas_antes_de_desistir(self):
        gerenciador = MagicMock()
        gerenciador.__enter__.return_value = object()
        gerenciador.__exit__.return_value = False

        with (
            patch.object(scraper, "sync_playwright", return_value=gerenciador),
            patch.object(
                scraper,
                "_raspar_site",
                side_effect=[RuntimeError("falha 1"), RuntimeError("falha 2"), ["ok"]],
            ) as raspar,
            patch.object(scraper.db, "registrar_status_site"),
            patch.object(scraper.time, "sleep"),
        ):
            site, _, itens, tentativas, erro = scraper._raspar_site_com_retentativa(
                "exemplo",
                {"nome": "Exemplo"},
                max_tentativas=3,
            )

        self.assertEqual(site, "exemplo")
        self.assertEqual(itens, ["ok"])
        self.assertEqual(tentativas, 3)
        self.assertIsNone(erro)
        self.assertEqual(raspar.call_count, 3)


if __name__ == "__main__":
    unittest.main()
