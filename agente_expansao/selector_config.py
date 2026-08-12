"""Regras seguras para editar configurações aprendidas de coleta."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import yaml

from .config import LOCAL_OVERRIDE_PATH, PROPOSAL_OVERRIDE_PATH, SELECTOR_HISTORY_PATH

REQUIRED_SELECTORS = ("card", "link", "titulo", "preco", "thumbnail")
SELECTOR_FIELDS = set(REQUIRED_SELECTORS) | {
    "bairro", "tipo", "status", "thumbnail_attr", "detalhe", "codigo",
}
CSS_FORBIDDEN = ("javascript:", "=>", "function(", "document.")
PAGINATION_TYPES = {"nenhuma", "auto", "botao", "rolagem", "url", "api_aprendida"}
FILTER_TYPES = {"select", "links", "nenhum"}


def _now() -> str:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(timespec="seconds")


def _read(path: Path) -> dict:
    if not path.is_file():
        return {"sites": {}}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict) or not isinstance(loaded.get("sites", {}), dict):
        raise ValueError("O arquivo de configurações aprendidas está inválido.")
    loaded.setdefault("sites", {})
    return loaded


def list_persisted_overrides(path: Path = LOCAL_OVERRIDE_PATH) -> dict:
    """Retorna somente fontes com bloco persistido, sem expor referências mutáveis."""
    return copy.deepcopy(_read(path)["sites"])


def config_signature(config: dict) -> str:
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Use uma URL http ou https válida.")
    return parsed.scheme, parsed.hostname.lower(), parsed.port


def _css(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"O seletor de {label} é obrigatório.")
    candidate = value.strip().lower()
    if candidate.startswith(("/", "./", "xpath=")) or "//" in candidate or any(token in candidate for token in CSS_FORBIDDEN):
        raise ValueError(f"O seletor de {label} deve ser CSS, não XPath ou JavaScript.")
    stack = []
    quote = ""
    escaped = False
    pairs = {")": "(", "]": "["}
    for char in value.strip():
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
        elif char in {"(", "["}:
            stack.append(char)
        elif char in pairs:
            if not stack or stack.pop() != pairs[char]:
                raise ValueError(f"O seletor de {label} possui delimitadores inválidos.")
        elif char in {"{", "}"}:
            raise ValueError(f"O seletor de {label} deve conter apenas o caminho CSS.")
    if quote or stack:
        raise ValueError(f"O seletor de {label} possui aspas ou delimitadores incompletos.")


def _safe_value(value: object, label: str) -> None:
    if isinstance(value, str):
        if "javascript:" in value.lower():
            raise ValueError(f"{label} não pode conter JavaScript.")
    elif isinstance(value, (int, float, bool)) or value is None:
        return
    elif isinstance(value, list):
        for item in value:
            _safe_value(item, label)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{label} contém uma chave inválida.")
            _safe_value(item, label)
    else:
        raise ValueError(f"{label} contém um valor inválido.")


def _validate_navigation(name: str, value: object) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError(f"A configuração de {name} deve ser um objeto.")
    _safe_value(value, name)
    kind = value.get("tipo")
    allowed = PAGINATION_TYPES if name == "paginação" else FILTER_TYPES
    if kind is not None and (not isinstance(kind, str) or kind not in allowed):
        raise ValueError(f"O tipo de {name} não é suportado.")
    for key, item in value.items():
        if key.endswith("selector") or key in {"seletor", "aplicar_selector", "botao_selector"}:
            if item:
                _css(item, key)
        if key.startswith(("max_", "espera_", "pagina_", "incremento", "parar_")):
            if not isinstance(item, (int, float)) or isinstance(item, bool) or item < 0 or item > 10000:
                raise ValueError(f"O valor de {key} em {name} deve ser numérico e seguro.")


def validate_override(site: dict) -> None:
    if not isinstance(site, dict):
        raise ValueError("A configuração da fonte está inválida.")
    list_url = site.get("listagem_url")
    base_url = site.get("base_url")
    if not isinstance(list_url, str):
        raise ValueError("Informe a URL da listagem.")
    if base_url and _origin(list_url) != _origin(base_url):
        raise ValueError("A URL da listagem deve permanecer na mesma origem da fonte.")
    _origin(list_url)
    selectors = site.get("seletores")
    if not isinstance(selectors, dict):
        raise ValueError("Informe os seletores da fonte.")
    for field in REQUIRED_SELECTORS:
        _css(selectors.get(field), field)
    for field, value in selectors.items():
        if field == "thumbnail_attr":
            if value and (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_:][-A-Za-z0-9_:.]*", value)):
                raise ValueError("thumbnail_attr deve ser o nome de um atributo HTML.")
        elif field in SELECTOR_FIELDS or field.endswith("_selector"):
            if value:
                _css(value, field)
        else:
            _safe_value(value, f"seletores.{field}")
    _validate_navigation("paginação", site.get("paginacao"))
    _validate_navigation("filtros", site.get("filtros"))


def _merge(previous: dict, draft: dict) -> dict:
    result = {**copy.deepcopy(previous), **copy.deepcopy(draft)}
    if isinstance(previous.get("seletores"), dict) and isinstance(draft.get("seletores"), dict):
        selectors = copy.deepcopy(previous["seletores"])
        for key, value in draft["seletores"].items():
            if value is None:
                selectors.pop(key, None)
            else:
                selectors[key] = copy.deepcopy(value)
        result["seletores"] = selectors
    return result


def _atomic_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _record(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def selector_history(site_key: str | None = None, path: Path = SELECTOR_HISTORY_PATH) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if site_key is None or event.get("site_key") == site_key:
            rows.append(event)
    return rows


def save_edited_override(
    site_key: str,
    draft: dict,
    *,
    tested_signature: str | None,
    test_result: dict | None,
    force: bool = False,
    justification: str = "",
    path: Path = LOCAL_OVERRIDE_PATH,
    history_path: Path = SELECTOR_HISTORY_PATH,
) -> dict:
    current = _read(path)
    previous = current["sites"].get(site_key)
    if not isinstance(previous, dict):
        raise ValueError("Esta fonte não possui configuração aprendida para editar.")
    proposed = _merge(previous, draft)
    validate_override(proposed)
    signature = config_signature(proposed)
    approved = bool(test_result and test_result.get("publicavel"))
    tested_current = tested_signature == signature
    if not tested_current or test_result is None:
        raise ValueError("Teste a configuração atual antes de salvar.")
    if not force and not approved:
        raise ValueError("Teste a configuração aprovada antes de salvar.")
    if force:
        if approved:
            raise ValueError("Use o salvamento normal quando o teste for aprovado.")
        if not justification.strip():
            raise ValueError("Explique por que deseja salvar mesmo com o aviso.")
    proposed["espera_seletor"] = proposed["seletores"]["card"]
    proposed["aprendido_em"] = _now()
    current["sites"][site_key] = proposed
    _atomic_yaml(path, current)
    try:
        _record(history_path, {
            "timestamp": _now(), "action": "save_forced" if force else "save",
            "site_key": site_key, "justification": justification.strip(),
            "validation": copy.deepcopy(test_result or {}), "previous": previous, "new": proposed,
        })
    except Exception:
        current["sites"][site_key] = previous
        _atomic_yaml(path, current)
        raise
    return copy.deepcopy(proposed)


def restore_previous_override(
    site_key: str,
    *,
    confirmation: bool,
    justification: str = "",
    path: Path = LOCAL_OVERRIDE_PATH,
    history_path: Path = SELECTOR_HISTORY_PATH,
) -> dict:
    if not confirmation:
        raise ValueError("Confirme a restauração da versão anterior.")
    current = _read(path)
    existing = current["sites"].get(site_key)
    if not isinstance(existing, dict):
        raise ValueError("Esta fonte não possui configuração aprendida para restaurar.")
    events = selector_history(site_key, history_path)
    if not events or not isinstance(events[-1].get("previous"), dict):
        raise ValueError("Não existe versão anterior disponível.")
    restored = copy.deepcopy(events[-1]["previous"])
    validate_override(restored)
    restored["espera_seletor"] = restored["seletores"]["card"]
    restored["aprendido_em"] = _now()
    current["sites"][site_key] = restored
    _atomic_yaml(path, current)
    try:
        _record(history_path, {
            "timestamp": _now(), "action": "restore", "site_key": site_key,
            "justification": justification.strip(), "validation": {"restored": True},
            "previous": existing, "new": restored,
        })
    except Exception:
        current["sites"][site_key] = existing
        _atomic_yaml(path, current)
        raise
    return copy.deepcopy(restored)


def proposal_override_is_stale(
    local_path: Path = LOCAL_OVERRIDE_PATH,
    proposal_path: Path = PROPOSAL_OVERRIDE_PATH,
) -> bool:
    return proposal_path.is_file() and (
        not local_path.is_file() or local_path.read_bytes() != proposal_path.read_bytes()
    )
