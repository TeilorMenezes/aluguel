import unittest
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import db
import scraper
from agente_expansao import resources
from agente_expansao import collection
from agente_expansao.visual_picker import _navigation_config


def _item(numero):
    return {
        "url": f"https://exemplo.test/imovel/{numero}",
        "titulo": f"Apartamento {numero}",
        "tipo": "Apartamento",
        "preco": 1000 + numero,
        "bairro": "Centro",
        "cidade": "Ipatinga",
        "thumbnail_url": f"https://exemplo.test/{numero}.jpg",
    }


class _PaginaComMais:
    def __init__(self):
        self.lote = 0

    def query_selector(self, _selector):
        return _BotaoMais(self) if self.lote < 3 else None

    def wait_for_timeout(self, _milliseconds):
        return None


class _BotaoMais:
    def __init__(self, page):
        self.page = page

    def is_visible(self):
        return True

    def click(self):
        self.page.lote += 1


class RoboLocalTest(unittest.TestCase):
    def test_infere_paginacao_somente_de_urls_observadas(self):
        strategy = scraper._template_url_numerica([
            "https://exemplo.test/busca?finalidade=alugar&page=2",
            "https://exemplo.test/busca?finalidade=alugar&page=3",
        ])
        self.assertEqual(
            strategy["url_template"],
            "https://exemplo.test/busca?finalidade=alugar&page={pagina}",
        )
        self.assertEqual(strategy["paginas_observadas"], [2, 3])

        offset = scraper._template_url_numerica([
            "https://exemplo.test/api?offset=20",
            "https://exemplo.test/api?offset=40",
        ])
        self.assertEqual(offset["incremento"], 20)

    def test_api_so_e_aprendida_com_paginas_repetidas(self):
        fallback = {"tipo": "botao", "botao_selector": ".mais"}
        unstable = scraper._estrategia_api_observada(
            [{"method": "GET", "url": "https://exemplo.test/api?page=2"}],
            fallback,
        )
        stable = scraper._estrategia_api_observada(
            [
                {"method": "GET", "url": "https://exemplo.test/api?page=2"},
                {"method": "GET", "url": "https://exemplo.test/api?page=3"},
            ],
            fallback,
            observed_items=91,
        )
        self.assertIsNone(unstable)
        self.assertEqual(stable["tipo"], "api_aprendida")
        self.assertEqual(stable["fallback"], fallback)
        self.assertEqual(stable["min_itens_esperados"], 72)

    def test_json_generico_exige_url_de_imovel(self):
        data = {"resultados": [
            {"url": "/imovel/1", "titulo": "Apartamento Centro", "valor": "R$ 1.500,00"},
            {"titulo": "Registro sem link", "valor": 900},
        ]}
        items = scraper._extrair_json_generico(
            data, {"base_url": "https://exemplo.test", "cidade_padrao": "Ipatinga"}
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://exemplo.test/imovel/1")
        self.assertEqual(items[0]["preco"], 1500.0)

    def test_ensino_visual_gera_configuracao_de_filtro(self):
        pagination, filters = _navigation_config(
            {
                "mode": "filtro",
                "selector": "select[name='bairro']",
                "metadata": {
                    "tipo": "select",
                    "opcoes": [{"value": "centro", "label": "Centro"}],
                    "apply_selector": "button.buscar",
                },
            },
            "https://exemplo.test/aluguel",
        )
        self.assertEqual(pagination["tipo"], "auto")
        self.assertEqual(filters["tipo"], "select")
        self.assertEqual(filters["aplicar_selector"], "button.buscar")

    def test_coleta_reutiliza_checkpoint_existente(self):
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            local_db = folder / "coleta.db"
            working = local_db.with_suffix(".working.db")
            working.write_bytes(b"checkpoint")
            override = folder / "override.yaml"
            history = folder / "history.jsonl"
            completed = SimpleNamespace(
                returncode=0,
                stdout='{"total": 0, "sites_retomados": ["pronta"]}\n',
                stderr="",
            )
            with (
                patch.object(collection, "LOCAL_COLLECTION_DB", local_db),
                patch.object(collection, "LOCAL_OVERRIDE_PATH", override),
                patch.object(collection, "STRATEGY_HISTORY_PATH", history),
                patch.object(collection.subprocess, "run", return_value=completed) as run,
                patch.object(collection, "collection_preview", return_value={"available": True}),
            ):
                result = collection.run_local_collection(["pronta"], fresh=False)
        self.assertIn("--resume", run.call_args.args[0])
        self.assertTrue(result["resumed"])
        self.assertEqual(result["sites_retomados"], ["pronta"])

    def test_aprendizado_visual_salva_navegacao_e_filtros(self):
        with TemporaryDirectory() as folder:
            override = Path(folder) / "override.yaml"
            with (
                patch.object(collection, "LOCAL_OVERRIDE_PATH", override),
                patch.object(collection, "configured_sites", return_value={"exemplo": {}}),
            ):
                collection.save_selector_override(
                    "exemplo",
                    "https://exemplo.test/aluguel",
                    {"card": ".card", "link": "a", "titulo": "h2", "preco": ".valor", "thumbnail": "img"},
                    pagination={"tipo": "rolagem", "max_rolagens": 80},
                    filters={"tipo": "links", "urls": ["https://exemplo.test/aluguel?bairro=centro"]},
                )
            saved = __import__("yaml").safe_load(override.read_text(encoding="utf-8"))
        self.assertEqual(saved["sites"]["exemplo"]["paginacao"]["tipo"], "rolagem")
        self.assertEqual(saved["sites"]["exemplo"]["filtros"]["tipo"], "links")

    def test_botao_acumula_lotes_mesmo_se_dom_for_substituido(self):
        page = _PaginaComMais()

        def extract(current_page, _config):
            # Simula lista virtualizada: cada lote substitui os cards anteriores.
            start = current_page.lote * 2
            return [_item(start + 1), _item(start + 2)]

        with patch.object(scraper, "_extrair_com_autocorrecao", side_effect=extract):
            items = scraper._raspar_com_botao(
                page,
                {"seletores": {"card": ".card"}},
                {
                    "botao_selector": ".load-more",
                    "max_cliques": 10,
                    "espera_apos_clique_ms": 0,
                },
            )

        self.assertEqual(len(items), 8)
        self.assertEqual(len({item["url"] for item in items}), 8)

    def test_concorrencia_adaptativa_reduz_sob_pressao(self):
        stressed = {
            "logical_cpus": 8,
            "physical_cpus": 4,
            "available_ram_gb": 1.5,
            "total_ram_gb": 16,
            "memory_percent": 91,
            "cpu_percent": 97,
        }
        with patch.object(resources, "capacity_snapshot", return_value=stressed):
            result = resources.recommended_workers("browser")
        self.assertEqual(result["workers"], 1)

    def test_concorrencia_adaptativa_usa_capacidade_disponivel(self):
        idle = {
            "logical_cpus": 8,
            "physical_cpus": 4,
            "available_ram_gb": 10,
            "total_ram_gb": 16,
            "memory_percent": 35,
            "cpu_percent": 15,
        }
        with patch.object(resources, "capacity_snapshot", return_value=idle):
            browser = resources.recommended_workers("browser")
            api = resources.recommended_workers("api")
        self.assertGreaterEqual(browser["workers"], 6)
        self.assertGreater(api["workers"], browser["workers"])

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
