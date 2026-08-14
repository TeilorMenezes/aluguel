import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agente_expansao.engine import ExpansionEngine, classify
from agente_expansao.integrations import ProjectAdapter
from agente_expansao.publication import (
    build_preview,
    merge_site_blocks,
    publish_pull_request,
    publish_snapshot_pull_request,
)
from agente_expansao import publication
from agente_expansao.storage import Repository


def candidate():
    return {
        "domain": "exemplo.com.br",
        "name": "Exemplo Imóveis",
        "state": "MG",
        "region": "Ipatinga",
        "city": "Ipatinga",
        "official_url": "https://exemplo.com.br",
        "rental_url": "https://exemplo.com.br/aluguel",
        "discovery_score": 0.81,
    }


class FakeAdapter:
    def inspect(self, url):
        return {
            "url": url,
            "confidence": 0.88,
            "publicavel": True,
            "platform": "teste",
            "selectors": {
                "card": ".card",
                "link": "a",
                "titulo": "h2",
                "preco": ".preco",
                "thumbnail": "img",
            },
            "taxas_campos": {
                "titulo": 1,
                "preco": 1,
                "thumbnail": 1,
                "link": 1,
            },
        }

    def validate_learned_selectors(self, url, selectors):
        return {
            "url": url,
            "confidence": 0.95,
            "qualidade_extracao": 0.95,
            "publicavel": True,
            "selectors": selectors,
            "learned_pattern": True,
        }


class AgentExpansionTest(unittest.TestCase):
    def test_project_adapter_normaliza_contrato_do_detector(self):
        raw = {
            "confianca": 0.91, "plataforma": "wordpress",
            "seletores": {"card": ".card"}, "evidencias": {"cards": 8},
        }
        with patch("agente_expansao.integrations.inspecionar_url", return_value=raw):
            result = ProjectAdapter().inspect("https://exemplo.test/aluguel")
        self.assertEqual(result["confidence"], 0.91)
        self.assertEqual(result["platform"], "wordpress")
        self.assertEqual(result["selectors"]["card"], ".card")
        self.assertEqual(result["evidence"]["cards"], 8)

    def test_stale_override_blocks_snapshot_publication_before_external_call(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            local, proposal = folder / "local.yaml", folder / "proposal.yaml"
            local.write_text("sites: {}\n", encoding="utf-8")
            proposal.write_text("sites: {exemplo: {}}\n", encoding="utf-8")
            with (
                patch.object(publication, "LOCAL_OVERRIDE_PATH", local),
                patch.object(publication, "PROPOSAL_OVERRIDE_PATH", proposal),
                patch.object(publication, "PROPOSAL_DB_PATH", folder / "db"),
                patch.object(publication, "PROPOSAL_MANIFEST_PATH", folder / "manifest"),
                patch.object(publication, "validate_snapshot", return_value={"valid": True}),
                patch.object(publication, "diagnose") as diagnose,
            ):
                with self.assertRaisesRegex(ValueError, "mudou"):
                    publish_snapshot_pull_request("PUBLICAR NO GITHUB")
            diagnose.assert_not_called()
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self.temp.name) / "agent.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_low_confidence_goes_to_quarantine(self):
        self.assertEqual(
            classify({"confidence": 0.4, "publicavel": False}), "quarentena"
        )

    def test_high_confidence_still_requires_review(self):
        self.assertEqual(
            classify({"confidence": 0.9, "publicavel": True}), "revisao"
        )

    def test_inspection_history_and_manual_approval(self):
        engine = ExpansionEngine(self.repo, FakeAdapter())
        candidate_id = engine.register_discovery([candidate()])[0]
        result = engine.inspect(candidate_id)
        self.assertEqual(result["status"], "revisao")

        current = self.repo.get_candidate(candidate_id)
        self.assertEqual(current["status"], "revisao")
        engine.approve(candidate_id, current["selectors"], "Validado visualmente.")
        approved = self.repo.get_candidate(candidate_id)
        self.assertEqual(approved["status"], "aprovado")
        self.assertEqual(
            self.repo.latest_correction("teste")["card"], ".card"
        )
        self.assertGreaterEqual(len(self.repo.list_events()), 4)

    def test_publication_preview_contains_only_approved_data(self):
        item = candidate()
        item["selectors"] = {
            "card": ".card", "link": "a", "preco": ".preco"
        }
        preview = build_preview([item])
        self.assertIn("exemplo:", preview)
        self.assertIn("listagem_url: https://exemplo.com.br/aluguel", preview)

    def test_learned_correction_is_revalidated_on_same_platform(self):
        engine = ExpansionEngine(self.repo, FakeAdapter())
        first_id = engine.register_discovery([candidate()])[0]
        engine.inspect(first_id)
        first = self.repo.get_candidate(first_id)
        learned = {**first["selectors"], "card": ".card-corrigido"}
        engine.approve(first_id, learned)

        second = {**candidate(), "domain": "outro.com.br",
                  "official_url": "https://outro.com.br",
                  "rental_url": "https://outro.com.br/aluguel"}
        second_id = engine.register_discovery([second])[0]
        result = engine.inspect(second_id)
        self.assertTrue(result["learned_pattern"])
        self.assertEqual(result["selectors"]["card"], ".card-corrigido")

    def test_publication_requires_exact_confirmation_before_any_tool(self):
        with self.assertRaises(ValueError):
            publish_pull_request([], "confirmar")

    def test_merge_preserves_comments_and_other_top_level_sections(self):
        current = (
            "# comentário importante\n"
            "sites:\n"
            "  atual:\n"
            "    nome: Atual\n\n"
            "agendamento:\n"
            "  horas: 6\n"
        )
        item = candidate()
        item["selectors"] = {"card": ".card", "link": "a", "preco": ".preco"}
        merged = merge_site_blocks(current, [item])
        self.assertIn("# comentário importante", merged)
        self.assertIn("  exemplo:", merged)
        self.assertIn("agendamento:\n  horas: 6", merged)
        self.assertLess(merged.index("  exemplo:"), merged.index("agendamento:"))


if __name__ == "__main__":
    unittest.main()
