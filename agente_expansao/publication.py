"""Publicação manual em branch + pull request, sem alterar produção."""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
from datetime import datetime
from urllib.parse import urlparse

import yaml

from .config import CONFIRMATION_PHRASE, PROJECT_ROOT, TARGET_REPOSITORY
from .config import LOCAL_OVERRIDE_PATH, PROPOSAL_DB_PATH, PROPOSAL_MANIFEST_PATH, PROPOSAL_OVERRIDE_PATH
from .selector_config import proposal_override_is_stale
from snapshot_publico import validate_snapshot


def _run(*args: str, timeout: int = 120) -> tuple[int, str]:
    process = subprocess.run(
        list(args),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return process.returncode, (process.stdout or process.stderr or "").strip()


def _site_key(candidate: dict) -> str:
    host = urlparse(candidate["official_url"]).hostname or candidate["domain"]
    base = host.lower().removeprefix("www.").split(".")[0]
    return re.sub(r"[^a-z0-9]+", "_", base).strip("_")


def site_block(candidate: dict) -> dict:
    return {
        "nome": candidate.get("name") or candidate["domain"],
        "base_url": candidate["official_url"],
        "listagem_url": candidate.get("rental_url") or candidate["official_url"],
        "cidade_padrao": candidate.get("city") or "",
        "espera_seletor": candidate["selectors"]["card"],
        "seletores": candidate["selectors"],
    }


def build_preview(candidates: list[dict]) -> str:
    sites = {_site_key(item): site_block(item) for item in candidates}
    return yaml.safe_dump({"sites": sites}, allow_unicode=True, sort_keys=False)


def merge_site_blocks(current_text: str, candidates: list[dict]) -> str:
    """Insere novos sites sem reformatar comentários e configurações existentes."""
    parsed = yaml.safe_load(current_text) or {}
    existing_sites = parsed.get("sites", {})
    additions = {}
    for candidate in candidates:
        key = _site_key(candidate)
        if key in existing_sites or key in additions:
            raise RuntimeError(f"A chave '{key}' já existe em sites_config.yaml.")
        additions[key] = site_block(candidate)

    lines = current_text.splitlines()
    sites_line = next(
        (index for index, line in enumerate(lines) if line.strip() == "sites:"), None
    )
    if sites_line is None:
        raise RuntimeError("A seção 'sites:' não existe em sites_config.yaml.")
    insertion = len(lines)
    for index in range(sites_line + 1, len(lines)):
        line = lines[index]
        if line and not line[0].isspace() and not line.lstrip().startswith("#"):
            insertion = index
            break

    dumped = yaml.safe_dump(additions, allow_unicode=True, sort_keys=False).rstrip()
    block = "\n".join("  " + line if line else line for line in dumped.splitlines())
    marker = [
        "",
        "  # Proposta gerada pelo Agente de Expansão Imobiliária.",
        block,
        "",
    ]
    merged = lines[:insertion] + marker + lines[insertion:]
    return "\n".join(merged).rstrip() + "\n"


def diagnose() -> dict:
    gh = shutil.which("gh")
    if not gh:
        return {"available": False, "reason": "GitHub CLI (gh) não instalado."}
    code, _ = _run(gh, "auth", "status", timeout=20)
    if code:
        return {"available": False, "reason": "GitHub CLI não autenticado."}
    code, remote = _run("git", "remote", "get-url", "origin", timeout=20)
    normalized = remote.lower().removesuffix(".git")
    if code or TARGET_REPOSITORY.lower() not in normalized:
        return {
            "available": False,
            "reason": f"O origin não aponta para {TARGET_REPOSITORY}.",
        }
    return {"available": True, "reason": "", "repository": TARGET_REPOSITORY}


def _gh_json(gh: str, *args: str) -> dict:
    code, output = _run(gh, *args)
    if code:
        raise RuntimeError(output)
    return json.loads(output)


def _gh_json_input(gh: str, endpoint: str, method: str, payload: dict) -> dict:
    process = subprocess.run(
        [gh, "api", endpoint, "-X", method, "--input", "-"],
        cwd=PROJECT_ROOT,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    if process.returncode:
        raise RuntimeError((process.stdout or process.stderr).strip())
    return json.loads(process.stdout or "{}")


def _create_branch(gh: str, prefix: str) -> str:
    base_ref = _gh_json(gh, "api", f"repos/{TARGET_REPOSITORY}/git/ref/heads/main")
    suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
    branch = f"codex/{prefix}-{suffix}"
    _gh_json_input(
        gh,
        f"repos/{TARGET_REPOSITORY}/git/refs",
        "POST",
        {"ref": f"refs/heads/{branch}", "sha": base_ref["object"]["sha"]},
    )
    return branch


def _upload_file(gh: str, branch: str, repository_path: str, local_path) -> None:
    code, output = _run(
        gh, "api",
        f"repos/{TARGET_REPOSITORY}/contents/{repository_path}?ref=main",
    )
    current_sha = ""
    if code == 0:
        current_sha = json.loads(output).get("sha", "")
    payload = {
        "message": f"Atualiza {repository_path} pelo Agente de Expansão",
        "content": base64.b64encode(local_path.read_bytes()).decode("ascii"),
        "branch": branch,
    }
    if current_sha:
        payload["sha"] = current_sha
    _gh_json_input(
        gh,
        f"repos/{TARGET_REPOSITORY}/contents/{repository_path}",
        "PUT",
        payload,
    )


def publish_snapshot_pull_request(confirmation: str) -> dict:
    """Publica o snapshot revisado em branch; nunca faz merge ou push em main."""
    if confirmation.strip() != CONFIRMATION_PHRASE:
        raise ValueError("Frase de confirmação inválida.")
    validation = validate_snapshot(PROPOSAL_DB_PATH, PROPOSAL_MANIFEST_PATH)
    if not validation.get("valid"):
        raise ValueError("Snapshot inválido: " + " ".join(validation.get("errors", [])))
    if not PROPOSAL_OVERRIDE_PATH.is_file():
        raise ValueError("Arquivo de aprendizado dos seletores ausente.")
    if proposal_override_is_stale(LOCAL_OVERRIDE_PATH, PROPOSAL_OVERRIDE_PATH):
        raise ValueError("A configuração aprendida mudou. Gere uma nova prévia antes de publicar.")
    diagnosis = diagnose()
    if not diagnosis["available"]:
        raise RuntimeError(diagnosis["reason"])

    gh = shutil.which("gh")
    branch = _create_branch(gh, "snapshot-imoveis")
    for repository_path, local_path in (
        ("public_data/imoveis.db", PROPOSAL_DB_PATH),
        ("public_data/manifest.json", PROPOSAL_MANIFEST_PATH),
        ("public_data/selectors_override.yaml", PROPOSAL_OVERRIDE_PATH),
    ):
        _upload_file(gh, branch, repository_path, local_path)
    code, url = _run(
        gh, "pr", "create", "--repo", TARGET_REPOSITORY,
        "--base", "main", "--head", branch,
        "--title", "Atualiza snapshot público de imóveis",
        "--body", (
            f"Snapshot local validado com {validation['total']} imóveis. "
            "O site mantém a coleta natural como alternativa. Requer revisão antes do merge."
        ),
    )
    if code:
        raise RuntimeError(url)
    return {"branch": branch, "pull_request_url": url.strip(), **validation}


def publish_pull_request(candidates: list[dict], confirmation: str) -> dict:
    """Cria uma proposta no GitHub. A branch main nunca é escrita diretamente."""
    if confirmation.strip() != CONFIRMATION_PHRASE:
        raise ValueError("Frase de confirmação inválida.")
    if not candidates:
        raise ValueError("Nenhum candidato aprovado foi selecionado.")
    diagnosis = diagnose()
    if not diagnosis["available"]:
        raise RuntimeError(diagnosis["reason"])

    gh = shutil.which("gh")
    repo = TARGET_REPOSITORY
    base_ref = _gh_json(gh, "api", f"repos/{repo}/git/ref/heads/main")
    base_sha = base_ref["object"]["sha"]
    suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
    branch = f"codex/agente-expansao-{suffix}"
    _gh_json(
        gh, "api", f"repos/{repo}/git/refs", "-X", "POST",
        "-f", f"ref=refs/heads/{branch}", "-f", f"sha={base_sha}",
    )

    current = _gh_json(
        gh, "api", f"repos/{repo}/contents/sites_config.yaml?ref=main"
    )
    current_text = base64.b64decode(current["content"]).decode("utf-8")
    content = merge_site_blocks(current_text, candidates)
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    _gh_json(
        gh, "api", f"repos/{repo}/contents/sites_config.yaml", "-X", "PUT",
        "-f", "message=Propõe imobiliárias aprovadas pelo Agente de Expansão",
        "-f", f"content={encoded}", "-f", f"branch={branch}",
        "-f", f"sha={current['sha']}",
    )
    code, url = _run(
        gh, "pr", "create", "--repo", repo, "--base", "main", "--head", branch,
        "--title", "Proposta do Agente de Expansão Imobiliária",
        "--body", (
            "Proposta criada manualmente pelo aplicativo local. "
            "Requer revisão humana antes do merge."
        ),
    )
    if code:
        raise RuntimeError(url)
    return {"branch": branch, "pull_request_url": url.strip()}
