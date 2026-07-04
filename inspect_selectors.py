"""
Script auxiliar para descobrir os seletores CSS corretos de um site.

Como usar:
    python inspect_selectors.py oliveira
    python inspect_selectors.py cirsa

Ele abre o site com um navegador VISÍVEL (headless=False), espera a página
carregar os imóveis via JavaScript, e salva:
  - um screenshot (data/debug_<site>.png)
  - o HTML já renderizado (data/debug_<site>.html)

Com o HTML renderizado em mãos, abra-o no navegador ou em um editor de texto
e procure a estrutura repetida de cada "card" de imóvel (Ctrl+F por "R$",
por exemplo, costuma levar direto ao preço). A partir daí você identifica
as classes CSS e preenche o sites_config.yaml.

Dica prática: no Chrome, clique com o botão direito num card de imóvel na
página real -> "Inspecionar" -> observe a classe do elemento que envolve
o card inteiro, o link, o preço, a imagem e o bairro (se existir).
"""
import sys
from pathlib import Path
import yaml
from playwright.sync_api import sync_playwright

CONFIG_PATH = Path(__file__).parent / "sites_config.yaml"
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def main(site_key: str):
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    if site_key not in cfg["sites"]:
        print(f"Site '{site_key}' não encontrado em sites_config.yaml")
        sys.exit(1)

    cfg_site = cfg["sites"][site_key]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        print(f"Abrindo {cfg_site['listagem_url']} ...")
        page.goto(cfg_site["listagem_url"], timeout=60000, wait_until="networkidle")

        print("Aguardando 5s extras para garantir que o JS terminou de renderizar...")
        page.wait_for_timeout(5000)

        screenshot_path = DATA_DIR / f"debug_{site_key}.png"
        html_path = DATA_DIR / f"debug_{site_key}.html"

        page.screenshot(path=str(screenshot_path), full_page=True)
        html_path.write_text(page.content(), encoding="utf-8")

        print(f"Screenshot salvo em: {screenshot_path}")
        print(f"HTML renderizado salvo em: {html_path}")
        print("\nO navegador vai ficar aberto por 60s para você inspecionar "
              "manualmente (botão direito -> Inspecionar num card de imóvel).")
        page.wait_for_timeout(60000)

        browser.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if len(sys.argv) != 2:
        print("Uso: python inspect_selectors.py <chave_do_site>")
        print("Exemplo: python inspect_selectors.py oliveira")
        sys.exit(1)
    main(sys.argv[1])
