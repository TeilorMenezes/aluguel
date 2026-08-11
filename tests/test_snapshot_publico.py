import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import yaml

import db
import scraper
import snapshot_publico
from agente_expansao import collection
from agente_expansao.integrations import ProjectAdapter
from snapshot_publico import PUBLIC_COLUMNS, create_snapshot, validate_snapshot


def make_source(path: Path, rows):
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            """CREATE TABLE imoveis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_key TEXT NOT NULL, imobiliaria TEXT NOT NULL, logo_url TEXT,
                url TEXT UNIQUE, titulo TEXT, tipo TEXT, preco REAL, bairro TEXT,
                cidade TEXT, thumbnail_url TEXT, latitude REAL, longitude REAL,
                coletado_em TEXT
            )"""
        )
        placeholders = ",".join("?" for _ in PUBLIC_COLUMNS)
        conn.executemany(
            f"INSERT INTO imoveis ({', '.join(PUBLIC_COLUMNS)}) VALUES ({placeholders})",
            rows,
        )
        conn.commit()


def row(site, number):
    return (
        site,
        f"Imobiliária {site}",
        "https://logo.test/x.png",
        f"https://{site}.test/imovel/{number}",
        f"Apartamento {number}",
        "Apartamento",
        1000 + number,
        "Centro",
        "Ipatinga",
        f"https://img.test/{site}-{number}.jpg",
        -19.4,
        -42.5,
        "2026-08-10T12:00:00",
    )


class PublicSnapshotTest(unittest.TestCase):
    def test_public_app_uses_snapshot_without_starting_scheduler(self):
        source = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")
        startup = source.split("# -----------------------------------------------------------------------", 1)[0]
        self.assertIn("db.init_public_db()", startup)
        self.assertNotIn("scheduler_runner", startup)
        self.assertNotIn("iniciar_agendador", startup)
        self.assertNotIn("coletar_sites_sem_dados_async", startup)

    def test_complete_snapshot_has_manifest_and_public_schema_only(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            source, output, manifest = temp / "source.db", temp / "public.db", temp / "manifest.json"
            make_source(source, [row("a", 1), row("b", 2)])
            result = create_snapshot(source, output, manifest)
            self.assertTrue(result["valid"])
            self.assertEqual(result["total"], 2)
            with closing(sqlite3.connect(output)) as conn:
                tables = {item[0] for item in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
            self.assertIn("imoveis", tables)
            self.assertNotIn("execucoes", tables)
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["schema_version"], 1)

    def test_partial_snapshot_replaces_selected_and_preserves_others(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            base_source, local = temp / "base-source.db", temp / "local.db"
            base, base_manifest = temp / "base.db", temp / "base.json"
            output, manifest = temp / "output.db", temp / "output.json"
            make_source(base_source, [row("a", 1), row("b", 1)])
            create_snapshot(base_source, base, base_manifest)
            make_source(local, [row("a", 2), row("c", 1)])
            result = create_snapshot(
                local, output, manifest, mode="partial",
                selected_site_keys={"a"}, base_snapshot=base,
            )
            self.assertTrue(result["valid"])
            with closing(sqlite3.connect(output)) as conn:
                values = conn.execute(
                    "SELECT site_key, url FROM imoveis ORDER BY site_key"
                ).fetchall()
            self.assertEqual(values, [
                ("a", "https://a.test/imovel/2"),
                ("b", "https://b.test/imovel/1"),
            ])

    def test_checksum_detects_modified_database(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            source, output, manifest = temp / "source.db", temp / "public.db", temp / "manifest.json"
            make_source(source, [row("a", 1)])
            create_snapshot(source, output, manifest)
            with closing(sqlite3.connect(output)) as conn:
                conn.execute("UPDATE imoveis SET titulo='alterado'")
                conn.commit()
            result = validate_snapshot(output, manifest)
            self.assertFalse(result["valid"])
            self.assertTrue(any("Checksum" in error for error in result["errors"]))

    def test_public_snapshot_is_copied_once_per_version(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            source, public_db, manifest = temp / "source.db", temp / "public.db", temp / "manifest.json"
            target = temp / "runtime" / "imoveis.db"
            make_source(source, [row("a", 1)])
            create_snapshot(source, public_db, manifest)
            with (
                patch.object(snapshot_publico, "PUBLIC_DB_PATH", public_db),
                patch.object(snapshot_publico, "PUBLIC_MANIFEST_PATH", manifest),
            ):
                self.assertTrue(snapshot_publico.install_public_snapshot_if_needed(target))
                self.assertFalse(snapshot_publico.install_public_snapshot_if_needed(target))

    def test_new_snapshot_replaces_existing_runtime_database(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            old_source, new_source = temp / "old.db", temp / "new.db"
            public_db, manifest = temp / "public.db", temp / "manifest.json"
            target = temp / "runtime" / "imoveis.db"
            make_source(old_source, [row("a", 1)])
            make_source(new_source, [row("a", 1), row("b", 2)])
            target.parent.mkdir(parents=True)
            old_source.replace(target)
            create_snapshot(new_source, public_db, manifest)
            with (
                patch.object(snapshot_publico, "PUBLIC_DB_PATH", public_db),
                patch.object(snapshot_publico, "PUBLIC_MANIFEST_PATH", manifest),
            ):
                self.assertTrue(snapshot_publico.install_public_snapshot_if_needed(target))
                self.assertFalse(snapshot_publico.install_public_snapshot_if_needed(target))
            with closing(sqlite3.connect(target)) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM imoveis").fetchone()[0], 2)

    def test_new_snapshot_replaces_database_open_for_reading(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            old_source, new_source = temp / "old.db", temp / "new.db"
            public_db, manifest = temp / "public.db", temp / "manifest.json"
            target = temp / "runtime" / "imoveis.db"
            make_source(old_source, [row("a", 1)])
            make_source(new_source, [row("a", 1), row("b", 2)])
            target.parent.mkdir(parents=True)
            old_source.replace(target)
            create_snapshot(new_source, public_db, manifest)
            open_reader = sqlite3.connect(target)
            try:
                open_reader.execute("SELECT COUNT(*) FROM imoveis").fetchone()
                with (
                    patch.object(snapshot_publico, "PUBLIC_DB_PATH", public_db),
                    patch.object(snapshot_publico, "PUBLIC_MANIFEST_PATH", manifest),
                ):
                    self.assertTrue(snapshot_publico.install_public_snapshot_if_needed(target))
            finally:
                open_reader.close()
            with closing(sqlite3.connect(target)) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM imoveis").fetchone()[0], 2)

    def test_public_initialization_does_not_create_collection_tables(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "runtime.db"
            with patch.object(db, "DB_PATH", target):
                db.init_public_db()
            with closing(sqlite3.connect(target)) as conn:
                tables = {
                    item[0] for item in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            self.assertIn("imoveis", tables)
            self.assertNotIn("execucoes", tables)
            self.assertNotIn("coletas_site", tables)

    def test_full_price_range_includes_properties_without_price(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "runtime.db"
            make_source(target, [row("a", 1), row("b", 2)])
            with closing(sqlite3.connect(target)) as conn:
                conn.execute("UPDATE imoveis SET preco = NULL WHERE site_key = 'b'")
                conn.commit()
            with patch.object(db, "DB_PATH", target):
                self.assertEqual(
                    db.contar_imoveis(
                        preco_min=0,
                        preco_max=2000,
                        incluir_sem_preco=True,
                    ),
                    2,
                )
                self.assertEqual(
                    db.contar_imoveis(
                        preco_min=0,
                        preco_max=2000,
                        incluir_sem_preco=False,
                    ),
                    1,
                )
                encontrados = db.listar_imoveis(
                    preco_min=0,
                    preco_max=2000,
                    incluir_sem_preco=True,
                )
            self.assertEqual({item["site_key"] for item in encontrados}, {"a", "b"})


class DiscoveryAndOverrideTest(unittest.TestCase):
    def test_automatic_pagination_strategy_is_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "overrides.yaml"
            with patch.dict(os.environ, {"IMOVEIS_SELECTORS_OVERRIDE": str(path)}):
                scraper._salvar_paginacao_aprendida(
                    "allex",
                    {
                        "tipo": "botao",
                        "botao_selector": "a.scroll-load",
                        "max_cliques": 50,
                    },
                )
            saved = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved["sites"]["allex"]["paginacao"]["botao_selector"],
                "a.scroll-load",
            )

    def test_discovery_ignores_domain_already_registered(self):
        adapter = ProjectAdapter()
        discovered = [{
            "dominio": "oliveiraimoveis.net",
            "base_url": "https://www.oliveiraimoveis.net",
            "url": "https://www.oliveiraimoveis.net/aluguel",
            "url_listagem": "https://www.oliveiraimoveis.net/aluguel",
            "nome_detectado": "Oliveira Imóveis",
            "municipio": "Ipatinga",
            "score": 90,
        }]
        with patch("agente_expansao.integrations.descobrir_urls_regiao", return_value=discovered):
            result = adapter.discover(
                state="MG", state_name="Minas Gerais", cities=["Ipatinga"]
            )
        self.assertEqual(result, [])
        self.assertEqual(len(adapter.last_skipped), 1)

    def test_scraper_accepts_new_site_from_approved_override(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            config_path, override_path = temp / "sites.yaml", temp / "override.yaml"
            config_path.write_text("sites: {}\n", encoding="utf-8")
            override_path.write_text(
                yaml.safe_dump({"sites": {"novo": {
                    "nome": "Nova Imobiliária",
                    "base_url": "https://nova.test",
                    "listagem_url": "https://nova.test/aluguel",
                    "cidade_padrao": "Ipatinga",
                    "espera_seletor": ".card",
                    "paginacao": {"tipo": "nenhuma"},
                    "seletores": {"card": ".card", "link": "a", "titulo": "h2", "preco": ".preco", "thumbnail": "img"},
                }}}),
                encoding="utf-8",
            )
            with (
                patch.object(scraper, "CONFIG_PATH", config_path),
                patch.dict(os.environ, {"IMOVEIS_SELECTORS_OVERRIDE": str(override_path)}),
            ):
                loaded = scraper.carregar_config()
            self.assertIn("novo", loaded["sites"])
            self.assertEqual(loaded["sites"]["novo"]["seletores"]["preco"], ".preco")

    def test_local_collection_worker_uses_isolated_database(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            local_db = temp / "coleta.db"
            override = temp / "overrides.yaml"
            with (
                patch.object(collection, "LOCAL_COLLECTION_DB", local_db),
                patch.object(collection, "LOCAL_OVERRIDE_PATH", override),
            ):
                result = collection.run_local_collection(
                    ["fonte_que_nao_existe"], fresh=True, timeout=30
                )
            self.assertTrue(local_db.is_file())
            self.assertEqual(result["total"], 0)
            self.assertNotEqual(local_db, snapshot_publico.PUBLIC_DB_PATH)


if __name__ == "__main__":
    unittest.main()
