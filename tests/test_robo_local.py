import unittest
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import db
import scraper
from url_safety import validar_url_publica, verificar_robots
from agente_expansao import resources
from agente_expansao import collection
from agente_expansao import selector_config
from agente_expansao.visual_picker import _navigation_config
from normalizacao import cidade_explicita_em_texto, normalizar_localizacao


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


class _ImageElement:
    def __init__(self, attrs=None, child=None):
        self.attrs = attrs or {}
        self.child = child

    def get_attribute(self, name):
        return self.attrs.get(name)

    def query_selector(self, _selector):
        return self.child


class _TextElement:
    def __init__(self, text):
        self.text = text

    def inner_text(self):
        return self.text


class _DetailPage:
    def __init__(self, by_selector):
        self.by_selector = by_selector

    def query_selector_all(self, selector):
        return self.by_selector.get(selector, [])

    def query_selector(self, selector):
        elementos = self.query_selector_all(selector)
        return elementos[0] if elementos else None

    def goto(self, *_args, **_kwargs):
        return None

    def wait_for_timeout(self, _milliseconds):
        return None

    def close(self):
        return None


class RoboLocalTest(unittest.TestCase):
    def test_thumbnail_pode_vir_de_container_srcset_ou_background(self):
        lazy = _ImageElement({"data-src": "/foto.webp"})
        self.assertEqual(
            scraper._url_imagem_elemento(_ImageElement(child=lazy)), "/foto.webp"
        )
        srcset = _ImageElement({"srcset": "/small.webp 400w, /large.webp 900w"})
        self.assertEqual(scraper._url_imagem_elemento(srcset), "/large.webp")
        background = _ImageElement({"style": "background-image: url('/bg.webp')"})
        self.assertEqual(scraper._url_imagem_elemento(background), "/bg.webp")
        style_preferido = _ImageElement({
            "style": "background: url('https://exemplo.test/bg.webp') 50% 50% no-repeat"
        })
        self.assertEqual(
            scraper._url_imagem_elemento(style_preferido, "style"),
            "https://exemplo.test/bg.webp",
        )
        self.assertEqual(
            scraper._normalizar_url_imagem(style_preferido.get_attribute("style")),
            "https://exemplo.test/bg.webp",
        )
        self.assertEqual(
            scraper._normalizar_url_imagem("url(https://exemplo.test/data-bg.jpg)"),
            "https://exemplo.test/data-bg.jpg",
        )
        self.assertIsNone(scraper._normalizar_url_imagem("background: cover"))
        self.assertEqual(
            scraper._primeira_url_srcset("/small.webp 320w, /large.webp 1280w"),
            "/large.webp",
        )

    def test_normalizacao_rejeita_navegacao_e_prioriza_cidade_explicita(self):
        self.assertEqual(normalizar_localizacao("Previous / Next", "Ipatinga"), (None, "Ipatinga"))
        self.assertEqual(
            cidade_explicita_em_texto("Loja, Lourdes - Governador Valadares/MG"),
            "Governador Valadares",
        )
        self.assertEqual(
            normalizar_localizacao("Cambuí, Campinas - SP", None),
            ("Cambuí", "Campinas"),
        )

    def test_localizacao_da_pagina_prioriza_json_ld_e_endereco(self):
        json_ld = '''
            {"@context": "https://schema.org", "address": {
                "addressNeighborhood": "Cidade Nobre",
                "addressLocality": "Ipatinga",
                "addressRegion": "MG"
            }}
        '''
        page = _DetailPage({
            'script[type="application/ld+json"]': [_TextElement(json_ld)],
            "address": [_TextElement("Outro bairro, Timóteo - MG")],
        })
        self.assertEqual(
            scraper._localizacao_da_pagina(page, {"cidade_padrao": "Ipatinga"}),
            ("Cidade Nobre", "Ipatinga"),
        )

    def test_localizacao_da_pagina_aceita_endereco_de_fonte_sem_json_ld(self):
        page = _DetailPage({
            "address": [_TextElement("Cambuí, Campinas - SP")],
        })
        self.assertEqual(
            scraper._localizacao_da_pagina(page, {"cidade_padrao": "Campinas"}),
            ("Cambuí", "Campinas"),
        )

    def test_localizacao_da_pagina_aceita_bairro_declarado_no_titulo(self):
        page = _DetailPage({
            "h1": [_TextElement("Apartamento para alugar no Bairro Veneza II")],
        })
        self.assertEqual(
            scraper._localizacao_da_pagina(page, {"cidade_padrao": "Ipatinga"}),
            ("Veneza Ii", "Ipatinga"),
        )

    def test_enriquecimento_consulta_detalhe_quando_bairro_esta_ausente(self):
        detalhe = _DetailPage({
            "h1": [_TextElement("Apartamento Bairro Veneza II")],
        })
        listagem = SimpleNamespace(
            context=SimpleNamespace(new_page=lambda: detalhe),
        )
        item = {
            "url": "https://exemplo.test/imovel/1",
            "titulo": "Apartamento Bairro Veneza II",
            "tipo": "Apartamento",
            "preco": 1200,
            "bairro": None,
            "cidade": "Ipatinga",
            "thumbnail_url": None,
        }
        scraper._enriquecer_itens_incompletos(
            listagem, [item], {"cidade_padrao": "Ipatinga"}
        )
        self.assertEqual(item["bairro"], "Veneza Ii")
        self.assertEqual(item["cidade"], "Ipatinga")

    def test_preco_prioriza_locacao_e_ignora_venda_condominio(self):
        self.assertEqual(
            scraper._parse_preco("Venda R$ 750.000 | Aluguel R$ 2.500 | Condomínio R$ 700"),
            2500.0,
        )
        self.assertEqual(
            scraper._parse_preco("Condomínio R$ 700 | aluguel R$ 2.500"),
            2500.0,
        )
        self.assertIsNone(scraper._parse_preco("Venda R$ 750.000"))
        self.assertIsNone(scraper._parse_preco("3 quartos, 80 m², código 1234"))

    def test_cidade_da_url_e_gate_de_saude_do_lote(self):
        self.assertEqual(
            scraper._cidade_da_url("https://exemplo.test/alugar/icara"), "Icara"
        )
        lote_saudavel = [
            {
                "url": f"https://exemplo.test/imovel/{numero}",
                "titulo": f"Apartamento {numero}", "preco": 1200,
                "cidade": "Icara", "thumbnail_url": "https://exemplo.test/foto.jpg",
            }
            for numero in range(3)
        ]
        self.assertTrue(scraper._saude_lote(lote_saudavel, baseline=3)["aceito"])
        lote_quebrado = [{**item, "titulo": "10 FOTOS"} for item in lote_saudavel]
        self.assertFalse(scraper._saude_lote(lote_quebrado, baseline=3)["aceito"])
        vazio = scraper._saude_lote([], baseline=3)
        self.assertEqual(vazio["urls_unicas"], 0)
        self.assertEqual(vazio["taxas"], {})

    def test_template_de_paginacao_por_caminho_tem_incremento(self):
        strategy = scraper._template_url_numerica([
            "https://exemplo.test/imoveis/page/2/"
        ])
        self.assertEqual(strategy["incremento"], 1)

    def test_url_safety_bloqueia_rede_privada(self):
        with patch("url_safety.socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ]):
            with self.assertRaises(ValueError):
                validar_url_publica("https://exemplo.test/aluguel")

    def test_robots_bloqueia_detector_quando_desautoriza(self):
        response = SimpleNamespace(
            status_code=200, url="https://exemplo.test/robots.txt",
            text="User-agent: *\nDisallow: /aluguel\n",
        )
        public_dns = [(2, 1, 6, "", ("8.8.8.8", 443))]
        with (
            patch("url_safety.socket.getaddrinfo", return_value=public_dns),
            patch("url_safety.requests.get", return_value=response),
        ):
            with self.assertRaises(ValueError):
                verificar_robots("https://exemplo.test/aluguel")

    def test_robots_nao_segue_redirecionamento_para_rede_privada(self):
        response = SimpleNamespace(
            status_code=302,
            url="https://exemplo.test/robots.txt",
            headers={"Location": "http://127.0.0.1/robots.txt"},
            text="",
        )
        public_dns = [(2, 1, 6, "", ("8.8.8.8", 443))]
        with (
            patch("url_safety.socket.getaddrinfo", return_value=public_dns),
            patch("url_safety.requests.get", return_value=response) as request,
        ):
            with self.assertRaises(ValueError):
                verificar_robots("https://exemplo.test/aluguel")
        request.assert_called_once()

        with patch("url_safety.socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("203.0.113.10", 443)),
        ]):
            # TEST-NET também é reservado e deve permanecer bloqueado.
            with self.assertRaises(ValueError):
                validar_url_publica("https://exemplo.test/aluguel")
    def test_editor_lists_overrides_and_preserves_unknown_fields(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "override.yaml"
            history = Path(folder) / "history.jsonl"
            path.write_text(
                "sites:\n  exemplo:\n    nome: Exemplo\n    base_url: https://exemplo.test\n"
                "    listagem_url: https://exemplo.test/aluguel\n    seletores:\n"
                "      card: .card\n      link: a\n      titulo: h2\n      preco: .preco\n"
                "      thumbnail: img\n      desconhecido: .extra\n    paginacao:\n      tipo: botao\n      limite_desconhecido: 7\n",
                encoding="utf-8",
            )
            listed = selector_config.list_persisted_overrides(path)
            draft = {"listagem_url": "https://exemplo.test/aluguel-2", "seletores": {"card": ".novo"}}
            saved = selector_config.save_edited_override(
                "exemplo", draft, tested_signature=selector_config.config_signature({**listed["exemplo"], **draft, "seletores": {**listed["exemplo"]["seletores"], **draft["seletores"]}}),
                test_result={"publicavel": True}, path=path, history_path=history,
            )
            self.assertEqual(saved["seletores"]["desconhecido"], ".extra")
            self.assertEqual(saved["paginacao"]["limite_desconhecido"], 7)
            self.assertEqual(saved["espera_seletor"], ".novo")

    def test_editor_rejects_unsafe_url_css_and_navigation(self):
        base = {
            "base_url": "https://exemplo.test", "listagem_url": "https://outro.test/aluguel",
            "seletores": {"card": ".card", "link": "a", "titulo": "h2", "preco": ".preco", "thumbnail": "img"},
        }
        with self.assertRaises(ValueError):
            selector_config.validate_override(base)
        base["listagem_url"] = "https://exemplo.test/aluguel"
        base["seletores"]["card"] = "//div"
        with self.assertRaises(ValueError):
            selector_config.validate_override(base)
        base["seletores"]["card"] = ".card"
        base["seletores"]["thumbnail"] = "img[src='foto.jpg'"
        with self.assertRaises(ValueError):
            selector_config.validate_override(base)
        base["seletores"]["thumbnail"] = "img[src='foto.jpg']"
        base["paginacao"] = {"tipo": "botao", "max_cliques": "muitos"}
        with self.assertRaises(ValueError):
            selector_config.validate_override(base)
        base["paginacao"] = {"tipo": "botao", "max_cliques": 10}
        base["filtros"] = {"tipo": "select", "seletor": "select.bairro"}
        selector_config.validate_override(base)

    def test_editor_accepts_mesma_origem_com_ou_sem_www(self):
        selector_config.validate_override({
            "base_url": "https://www.exemplo.test",
            "listagem_url": "https://exemplo.test/aluguel",
            "seletores": {
                "card": ".card", "link": "a", "titulo": "h2",
                "preco": ".preco", "thumbnail": "img",
            },
        })

    def test_editor_requires_current_test_or_forced_justification_and_writes_history(self):
        with TemporaryDirectory() as folder:
            path, history = Path(folder) / "override.yaml", Path(folder) / "history.jsonl"
            data = {"sites": {"exemplo": {"base_url": "https://exemplo.test", "listagem_url": "https://exemplo.test/a", "seletores": {"card": ".card", "link": "a", "titulo": "h2", "preco": ".preco", "thumbnail": "img"}}}}
            path.write_text(__import__("yaml").safe_dump(data), encoding="utf-8")
            draft = {"seletores": {"card": ".novo"}}
            with self.assertRaises(ValueError):
                selector_config.save_edited_override("exemplo", draft, tested_signature=None, test_result=None, path=path, history_path=history)
            with self.assertRaises(ValueError):
                selector_config.save_edited_override("exemplo", draft, tested_signature="antigo", test_result={"publicavel": True}, path=path, history_path=history)
            with self.assertRaises(ValueError):
                selector_config.save_edited_override("exemplo", draft, tested_signature=None, test_result={"publicavel": False}, force=True, path=path, history_path=history)
            proposed = selector_config._merge(data["sites"]["exemplo"], draft)
            current_signature = selector_config.config_signature(proposed)
            with self.assertRaises(ValueError):
                selector_config.save_edited_override(
                    "exemplo", draft, tested_signature=current_signature,
                    test_result={"publicavel": True}, force=True,
                    justification="Não deve forçar", path=path,
                    history_path=history,
                )
            with self.assertRaises(ValueError):
                selector_config.save_edited_override(
                    "exemplo", draft, tested_signature=None,
                    test_result={"publicavel": False}, force=True,
                    justification="Conferido manualmente", path=path,
                    history_path=history,
                )
            saved = selector_config.save_edited_override(
                "exemplo", draft, tested_signature=current_signature,
                test_result={"publicavel": False}, force=True,
                justification="Conferido manualmente", path=path,
                history_path=history,
            )
            self.assertEqual(saved["seletores"]["card"], ".novo")
            self.assertEqual(selector_config.selector_history("exemplo", history)[0]["action"], "save_forced")
            restored = selector_config.restore_previous_override("exemplo", confirmation=True, path=path, history_path=history)
            self.assertEqual(restored["seletores"]["card"], ".card")

    def test_editor_failure_keeps_previous_file(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "override.yaml"
            original = "sites:\n  exemplo:\n    base_url: https://exemplo.test\n    listagem_url: https://exemplo.test/a\n    seletores:\n      card: .card\n      link: a\n      titulo: h2\n      preco: .preco\n      thumbnail: img\n"
            path.write_text(original, encoding="utf-8")
            with self.assertRaises(ValueError):
                selector_config.save_edited_override("exemplo", {"seletores": {"card": "//invalido"}}, tested_signature=None, test_result=None, path=path, history_path=Path(folder) / "history.jsonl")
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_editor_uses_atomic_write(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "override.yaml"
            history = Path(folder) / "history.jsonl"
            original = "sites:\n  exemplo:\n    base_url: https://exemplo.test\n    listagem_url: https://exemplo.test/a\n    seletores:\n      card: .card\n      link: a\n      titulo: h2\n      preco: .preco\n      thumbnail: img\n"
            path.write_text(original, encoding="utf-8")
            current = selector_config.list_persisted_overrides(path)["exemplo"]
            draft = {"seletores": {"card": ".novo"}}
            signature = selector_config.config_signature({**current, "seletores": {**current["seletores"], **draft["seletores"]}})
            with patch.object(selector_config.os, "replace", side_effect=OSError("falha")):
                with self.assertRaises(OSError):
                    selector_config.save_edited_override("exemplo", draft, tested_signature=signature, test_result={"publicavel": True}, path=path, history_path=history)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(Path(folder).glob(".override.yaml.*.tmp")), [])

    def test_editor_rolls_back_when_history_cannot_be_recorded(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "override.yaml"
            history = Path(folder) / "history.jsonl"
            original = {
                "sites": {
                    "exemplo": {
                        "base_url": "https://exemplo.test",
                        "listagem_url": "https://exemplo.test/a",
                        "seletores": {
                            "card": ".card", "link": "a", "titulo": "h2",
                            "preco": ".preco", "thumbnail": "img",
                        },
                    }
                }
            }
            path.write_text(
                __import__("yaml").safe_dump(original, sort_keys=False),
                encoding="utf-8",
            )
            draft = {"seletores": {"card": ".novo"}}
            proposed = selector_config._merge(original["sites"]["exemplo"], draft)
            signature = selector_config.config_signature(proposed)
            with patch.object(selector_config, "_record", side_effect=OSError("sem espaço")):
                with self.assertRaises(OSError):
                    selector_config.save_edited_override(
                        "exemplo", draft, tested_signature=signature,
                        test_result={"publicavel": True}, path=path,
                        history_path=history,
                    )
            restored = __import__("yaml").safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(restored, original)

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
            {"url": "/imovel/1", "titulo": "Apartamento Centro", "valor": "R$ 1,200"},
            {"titulo": "Registro sem link", "valor": 900},
        ]}
        items = scraper._extrair_json_generico(
            data, {"base_url": "https://exemplo.test", "cidade_padrao": "Ipatinga"}
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://exemplo.test/imovel/1")
        self.assertEqual(items[0]["preco"], 1200.0)

    def test_preco_entende_milhar_com_virgula_e_formatos_internacionais(self):
        casos = {
            "R$ 1,200": 1200.0,
            "1,200": 1200.0,
            "R$ 12,345": 12345.0,
            "R$ 1,200.00": 1200.0,
            "R$ 1.200,00": 1200.0,
            "R$ 1 200,00": 1200.0,
            "R$ 1200,50": 1200.5,
            "R$ 1,20": 1.2,
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(scraper._parse_preco(texto), esperado)
        self.assertIsNone(scraper._parse_preco("Sob consulta"))

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

    def test_aprendizado_visual_permite_limpar_paginacao_e_filtros(self):
        with TemporaryDirectory() as folder:
            override = Path(folder) / "override.yaml"
            override.write_text(
                "sites:\n  exemplo:\n    paginacao:\n      tipo: url\n"
                "    filtros:\n      tipo: links\n",
                encoding="utf-8",
            )
            with (
                patch.object(collection, "LOCAL_OVERRIDE_PATH", override),
                patch.object(collection, "configured_sites", return_value={"exemplo": {}}),
            ):
                collection.save_selector_override(
                    "exemplo",
                    "https://exemplo.test/aluguel",
                    {"card": ".card", "link": "a", "titulo": "h2", "preco": ".valor", "thumbnail": "img"},
                    pagination={},
                    filters={},
                )
            saved = __import__("yaml").safe_load(override.read_text(encoding="utf-8"))
        self.assertEqual(saved["sites"]["exemplo"]["paginacao"], {})
        self.assertEqual(saved["sites"]["exemplo"]["filtros"], {})

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
