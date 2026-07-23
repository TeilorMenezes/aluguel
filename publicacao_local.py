"""Publicação segura das configurações aprovadas no computador local."""
from datetime import datetime
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).parent
ARQUIVOS_PUBLICAVEIS = ("sites_config.yaml", "detector_patterns.yaml")


def _executar(*args, timeout=60):
    processo = subprocess.run(
        list(args),
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    saida = (processo.stdout or processo.stderr or "").strip()
    return processo.returncode, saida


def _gh_executavel():
    encontrado = shutil.which("gh")
    if encontrado:
        return encontrado
    caminho_windows = Path("C:/Program Files/GitHub CLI/gh.exe")
    return str(caminho_windows) if caminho_windows.is_file() else ""


def diagnosticar_publicacao():
    """Informa se este ambiente pode publicar configurações na branch main."""
    codigo, raiz = _executar("git", "rev-parse", "--show-toplevel")
    if codigo != 0 or Path(raiz).resolve() != ROOT.resolve():
        return {
            "disponivel": False,
            "motivo": "Este ambiente não é a cópia Git local do projeto.",
            "alterados": [],
        }

    codigo, branch = _executar("git", "branch", "--show-current")
    if codigo != 0 or branch != "main":
        return {
            "disponivel": False,
            "motivo": "Mude o projeto para a branch main antes de publicar.",
            "alterados": [],
            "branch": branch,
        }

    gh = _gh_executavel()
    if not gh:
        return {
            "disponivel": False,
            "motivo": "GitHub CLI não está instalado neste computador.",
            "alterados": [],
            "branch": branch,
        }
    codigo, _ = _executar(gh, "auth", "status", timeout=20)
    if codigo != 0:
        return {
            "disponivel": False,
            "motivo": "O GitHub CLI não está autenticado.",
            "alterados": [],
            "branch": branch,
        }

    codigo, status = _executar(
        "git",
        "status",
        "--porcelain",
        "--",
        *ARQUIVOS_PUBLICAVEIS,
    )
    alterados = []
    if codigo == 0:
        for linha in status.splitlines():
            caminho = linha[3:].strip().strip('"')
            if caminho:
                alterados.append(caminho)
    codigo, ahead = _executar(
        "git",
        "rev-list",
        "--count",
        "origin/main..HEAD",
    )
    commits_pendentes = int(ahead) if codigo == 0 and ahead.isdigit() else 0
    return {
        "disponivel": True,
        "motivo": "",
        "alterados": sorted(set(alterados)),
        "branch": branch,
        "commits_pendentes": commits_pendentes,
    }


def publicar_configuracoes():
    """Cria um commit apenas com configurações e envia diretamente à main."""
    diagnostico = diagnosticar_publicacao()
    if not diagnostico["disponivel"]:
        return {"ok": False, "mensagem": diagnostico["motivo"]}
    if not diagnostico["alterados"] and not diagnostico.get("commits_pendentes"):
        return {
            "ok": False,
            "mensagem": "Não existem configurações novas para publicar.",
        }

    codigo, saida = _executar("git", "fetch", "origin", "main", timeout=120)
    if codigo != 0:
        return {"ok": False, "mensagem": f"Não foi possível consultar o GitHub: {saida}"}

    codigo, _ = _executar(
        "git",
        "merge-base",
        "--is-ancestor",
        "origin/main",
        "HEAD",
    )
    if codigo != 0:
        return {
            "ok": False,
            "mensagem": (
                "A versão do GitHub está à frente desta cópia. "
                "Atualize o projeto antes de publicar."
            ),
        }

    if diagnostico["alterados"]:
        codigo, saida = _executar("git", "add", "--", *ARQUIVOS_PUBLICAVEIS)
        if codigo != 0:
            return {"ok": False, "mensagem": f"Não foi possível preparar os arquivos: {saida}"}

        mensagem = "Atualiza imobiliárias aprovadas localmente"
        codigo, saida = _executar("git", "commit", "-m", mensagem)
        if codigo != 0:
            return {"ok": False, "mensagem": f"Não foi possível criar o commit: {saida}"}

    codigo, saida = _executar("git", "push", "origin", "main", timeout=120)
    if codigo != 0:
        return {
            "ok": False,
            "mensagem": (
                "O commit foi criado localmente, mas o envio falhou. "
                f"Detalhes: {saida}"
            ),
        }

    codigo, commit = _executar("git", "rev-parse", "--short", "HEAD")
    return {
        "ok": True,
        "mensagem": "Configurações enviadas. O Streamlit iniciará um novo deploy.",
        "commit": commit if codigo == 0 else "",
        "arquivos": diagnostico["alterados"],
        "publicado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
