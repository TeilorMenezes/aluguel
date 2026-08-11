"""Orquestração determinística; IA é apenas um ponto de extensão."""
from __future__ import annotations

from typing import Protocol

from .config import HIGH_CONFIDENCE, QUARANTINE_CONFIDENCE
from .integrations import ProjectAdapter
from .storage import Repository


class AmbiguityResolver(Protocol):
    """Contrato futuro para API ou modelo local pequeno."""

    def review(self, candidate: dict, inspection: dict) -> dict: ...


class DisabledAI:
    def review(self, candidate: dict, inspection: dict) -> dict:
        return {
            "used": False,
            "reason": "IA desativada; revisão humana necessária.",
        }


def classify(inspection: dict) -> str:
    """Classifica sem jamais aprovar ou publicar automaticamente."""
    if inspection.get("error"):
        return "erro"
    confidence = float(inspection.get("confidence", 0))
    if inspection.get("publicavel") and confidence >= HIGH_CONFIDENCE:
        return "revisao"
    if confidence < QUARANTINE_CONFIDENCE or not inspection.get("publicavel"):
        return "quarentena"
    return "revisao"


class ExpansionEngine:
    def __init__(
        self,
        repository: Repository,
        adapter: ProjectAdapter | None = None,
        ambiguity_resolver: AmbiguityResolver | None = None,
    ):
        self.repository = repository
        self.adapter = adapter or ProjectAdapter()
        self.ai = ambiguity_resolver or DisabledAI()

    def register_discovery(self, items: list[dict]) -> list[int]:
        return [self.repository.upsert_candidate(item) for item in items]

    def inspect(self, candidate_id: int) -> dict:
        candidate = self.repository.get_candidate(candidate_id)
        if not candidate:
            raise ValueError("Candidato não encontrado.")
        url = candidate.get("rental_url") or candidate["official_url"]
        result = self.adapter.inspect(url)
        learned = self.repository.latest_correction(result.get("platform", ""))
        if (
            learned
            and not result.get("error")
            and hasattr(self.adapter, "validate_learned_selectors")
        ):
            try:
                learned_result = self.adapter.validate_learned_selectors(url, learned)
                if learned_result.get("qualidade_extracao", 0) >= result.get(
                    "qualidade_extracao", 0
                ):
                    learned_result["platform"] = result.get("platform", "")
                    learned_result["confidence"] = max(
                        float(result.get("confidence", 0)),
                        float(learned_result.get("qualidade_extracao", 0)),
                    )
                    result = learned_result
            except Exception as exc:
                self.repository.log(
                    "aprendizado",
                    f"O padrão aprendido não pôde ser revalidado: {exc}",
                    candidate_id=candidate_id,
                    level="warning",
                )
        status = classify(result)
        if status in {"revisao", "quarentena"} and 0.55 <= float(
            result.get("confidence", 0)
        ) < HIGH_CONFIDENCE:
            result["ai_review"] = self.ai.review(candidate, result)
        self.repository.save_inspection(candidate_id, result, status)
        return {**result, "status": status}

    def approve(
        self, candidate_id: int, selectors: dict, note: str = "", learn: bool = True
    ) -> None:
        candidate = self.repository.get_candidate(candidate_id)
        if not candidate:
            raise ValueError("Candidato não encontrado.")
        if not {"card", "link", "preco"}.issubset(selectors):
            raise ValueError("Card, link e preço são seletores obrigatórios.")
        if learn:
            self.repository.save_correction(
                candidate_id, candidate.get("platform") or "desconhecida", selectors, note
            )
        self.repository.set_status(
            candidate_id, "aprovado",
            "Candidato aprovado manualmente pelo administrador."
        )
