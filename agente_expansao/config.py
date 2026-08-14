from pathlib import Path
import os


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
DATA_DIR = Path(os.getenv("AGENTE_EXPANSAO_DATA_DIR", APP_DIR / "data"))
DB_PATH = Path(os.getenv("AGENTE_EXPANSAO_DB", DATA_DIR / "agente_expansao.db"))
LOCAL_COLLECTION_DB = DATA_DIR / "coleta_local.db"
LOCAL_OVERRIDE_PATH = DATA_DIR / "selectors_override.yaml"
STRATEGY_HISTORY_PATH = DATA_DIR / "strategy_history.jsonl"
SELECTOR_HISTORY_PATH = DATA_DIR / "selector_config_history.jsonl"
PROPOSAL_DIR = DATA_DIR / "proposta_publica"
PROPOSAL_DB_PATH = PROPOSAL_DIR / "imoveis.db"
PROPOSAL_MANIFEST_PATH = PROPOSAL_DIR / "manifest.json"
PROPOSAL_OVERRIDE_PATH = PROPOSAL_DIR / "selectors_override.yaml"
PUBLIC_BASE_CACHE_DIR = DATA_DIR / "base_publica"
TARGET_REPOSITORY = "TeilorMenezes/aluguel"
CONFIRMATION_PHRASE = "PUBLICAR NO GITHUB"

# Nenhuma dessas faixas publica automaticamente. Elas apenas organizam a revisão.
HIGH_CONFIDENCE = 0.78
QUARANTINE_CONFIDENCE = 0.62
