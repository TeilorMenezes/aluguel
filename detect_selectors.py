"""Analisa um HTML renderizado e sugere seletores para sites_config.yaml.

Uso: python detect_selectors.py data/debug_nome-do-site.html
"""
import json
import sys
from pathlib import Path

from detector import detectar_seletores


if len(sys.argv) != 2:
    print("Uso: python detect_selectors.py data/debug_nome-do-site.html")
    raise SystemExit(1)

caminho = Path(sys.argv[1])
if not caminho.is_file():
    print(f"Arquivo não encontrado: {caminho}")
    raise SystemExit(1)

resultado = detectar_seletores(caminho.read_text(encoding="utf-8"))
print(json.dumps(resultado, ensure_ascii=False, indent=2))
