import subprocess
import sys
import hmac
import html
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
import streamlit.components.v1 as components
import folium
import yaml
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

import db
from detector import detectar_seletores, inspecionar_url, salvar_padrao
from descobrir_sites import descobrir_urls_vale_aco
from scheduler_runner import iniciar_agendador, rodar_agora_async, rodar_site_agora_async

st.set_page_config(page_title="Mapa do Aluguel", layout="wide", page_icon="🏠")


@st.cache_resource
def garantir_chromium_instalado():
    """No Streamlit Community Cloud não existe um passo manual de
    'playwright install chromium' — então instalamos aqui, uma única vez
    por sessão do servidor (cacheado). No seu PC local isso é ignorado
    rapidamente, pois o Chromium já está instalado."""
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=False,
            capture_output=True,
            timeout=300,
        )
    except Exception:
        pass
    return True


garantir_chromium_instalado()

db.init_db()
db.remover_duplicata_diferencial()
iniciar_agendador()  # cacheado via variável de módulo (só cria os jobs uma vez)

# -----------------------------------------------------------------------
# Estilos (thumbnail com selo redondo da imobiliária)
# -----------------------------------------------------------------------
st.markdown("""
<style>
.card-imovel {
    border: 1px solid #d8d8d8;
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 18px;
    background-color: #ffffff !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.12);
}
.thumb-wrap {
    position: relative;
    width: 100%;
    height: 180px;
    background-color: #f2f2f2;
    background-position: center;
    background-size: cover;
    background-repeat: no-repeat;
}
.thumb-wrap img.thumb {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
}
.thumb-wrap.thumb-missing::after {
    content: "Imagem indisponível";
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    color: #737373;
    font-size: 0.9rem;
}
.logo-badge {
    position: absolute;
    bottom: 8px;
    left: 8px;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    border: 2px solid white;
    background-color: #ffffff !important;
    object-fit: cover;
    box-shadow: 0 1px 4px rgba(0,0,0,0.3);
}
.card-body {
    padding: 10px 14px 14px 14px;
    background-color: #ffffff !important;
}
.card-titulo {
    color: #1a1a1a !important;
    font-weight: 700;
    font-size: 0.98rem;
    line-height: 1.3;
}
.card-preco {
    font-size: 1.1rem;
    font-weight: 700;
    color: #1a7a3c !important;
    margin: 4px 0;
}
.card-bairro {
    color: #444444 !important;
    font-size: 0.9rem;
}
.card-imobiliaria {
    font-size: 0.8rem;
    color: #888888 !important;
    margin-top: 4px;
}
.tipo-badge {
    position: absolute;
    top: 8px;
    left: 8px;
    background-color: rgba(0,0,0,0.65) !important;
    color: #ffffff !important;
    font-size: 0.72rem;
    font-weight: 600;
    padding: 3px 9px;
    border-radius: 20px;
}
.card-tipo {
    display: inline-block;
    color: #555555;
    font-size: 0.78rem;
    font-weight: 600;
    margin-bottom: 4px;
}

/* Identidade visual do Mapa do Aluguel */
:root {
    --mv-ink: #162521;
    --mv-muted: #61716c;
    --mv-green: #0b4f49;
    --mv-green-dark: #073f3b;
    --mv-mint: #eef7f3;
    --mv-yellow: #f1c45b;
    --mv-line: #dce5e1;
}
.stApp {
    color: var(--mv-ink);
    background: #ffffff;
}
[data-testid="stSidebar"] {
    background: #f7faf8;
    border-right: 1px solid var(--mv-line);
}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: var(--mv-green-dark);
}
.mv-hero {
    position: relative;
    display: grid;
    grid-template-columns: 1.08fr .92fr;
    gap: 3.5rem;
    align-items: center;
    min-height: 31rem;
    margin: -1rem -1rem 1.25rem;
    padding: 3.5rem 3.25rem;
    overflow: hidden;
    background:
        radial-gradient(circle at 83% 28%, rgba(188, 222, 212, .55), transparent 24%),
        linear-gradient(135deg, #fbfdfc 0%, #f1f8f5 60%, #f9f5e7 100%);
    border: 1px solid #e6efeb;
    border-radius: 1.75rem;
}
.mv-hero::before {
    content: "";
    position: absolute;
    inset: 0;
    opacity: .18;
    background-image: radial-gradient(#56877b 0.7px, transparent 0.7px);
    background-size: 24px 24px;
    mask-image: linear-gradient(to right, black, transparent 60%);
}
.mv-hero-copy,
.mv-map-shell {
    position: relative;
    z-index: 1;
}
.mv-eyebrow {
    display: flex;
    align-items: center;
    gap: .6rem;
    margin-bottom: 1.1rem;
    color: #12645b;
    font-size: .75rem;
    font-weight: 800;
    letter-spacing: .08em;
    text-transform: uppercase;
}
.mv-eyebrow::before {
    content: "";
    width: 1.5rem;
    height: 2px;
    background: var(--mv-yellow);
}
.mv-hero h1 {
    max-width: 44rem;
    margin: 0 0 1.35rem;
    color: var(--mv-ink);
    font-size: clamp(3rem, 5vw, 4.8rem);
    line-height: 1.02;
    letter-spacing: -.055em;
}
.mv-hero h1 em {
    position: relative;
    color: #12645b;
    font-style: normal;
}
.mv-hero h1 em::after {
    content: "";
    position: absolute;
    z-index: -1;
    right: 0;
    bottom: .1rem;
    left: 0;
    height: .55rem;
    background: rgba(241, 196, 91, .62);
    border-radius: 999px;
}
.mv-hero-copy > p {
    max-width: 39rem;
    margin: 0;
    color: var(--mv-muted);
    font-size: 1.05rem;
    line-height: 1.7;
}
.mv-map-shell {
    min-height: 24rem;
    padding: .55rem;
    background: white;
    border-radius: 1.7rem;
    box-shadow: 0 2rem 4.5rem rgba(11, 79, 73, .16);
    transform: rotate(1.3deg);
}
.mv-map-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 3.25rem;
    padding: 0 1rem;
    color: var(--mv-ink);
    font-size: .78rem;
    font-weight: 800;
}
.mv-region-pill {
    padding: .35rem .6rem;
    color: #12645b;
    background: var(--mv-mint);
    border-radius: 999px;
    font-size: .63rem;
}
.mv-map {
    position: relative;
    height: 23.25rem;
    overflow: hidden;
    background:
        radial-gradient(circle at 75% 24%, #d2e7dd 0 9%, transparent 9.5%),
        radial-gradient(circle at 20% 78%, #d2e7dd 0 12%, transparent 12.5%),
        linear-gradient(135deg, #ebf3ef, #dcebe5);
    border-radius: 1.25rem;
}
.mv-road {
    position: absolute;
    width: 125%;
    height: .55rem;
    left: -12%;
    background: white;
    border: 1px solid #cdded8;
    border-radius: 999px;
}
.mv-road-a { top: 36%; transform: rotate(-16deg); }
.mv-road-b { top: 54%; transform: rotate(48deg); }
.mv-road-c { top: 76%; transform: rotate(14deg); }
.mv-river {
    position: absolute;
    width: 125%;
    height: 2.8rem;
    left: -12%;
    bottom: 13%;
    background: #b7d9dc;
    border-radius: 45%;
    opacity: .8;
    transform: rotate(-11deg);
}
.mv-pin {
    position: absolute;
    width: 1.65rem;
    height: 1.65rem;
    display: grid;
    place-items: center;
    color: var(--mv-yellow);
    background: var(--mv-green);
    border: 3px solid white;
    border-radius: 50% 50% 50% 4px;
    box-shadow: 0 .4rem .8rem rgba(11, 79, 73, .28);
    transform: rotate(-45deg);
}
.mv-pin span { transform: rotate(45deg); font-size: .55rem; }
.mv-pin-a { top: 22%; left: 24%; }
.mv-pin-b { top: 47%; right: 22%; }
.mv-pin-c { bottom: 17%; left: 44%; }
.mv-map-label {
    position: absolute;
    top: 35%;
    left: 17%;
    padding: .25rem .45rem;
    color: #536c65;
    background: rgba(255,255,255,.78);
    border-radius: .35rem;
    font-size: .6rem;
    font-weight: 700;
}
.mv-search-intro {
    margin: 1.7rem 0 .75rem;
}
.mv-search-intro h2 {
    margin: 0;
    color: var(--mv-ink);
    font-size: 1.55rem;
    letter-spacing: -.03em;
}
div[data-testid="stForm"] {
    padding: 1.15rem;
    background: white;
    border: 1px solid var(--mv-line);
    border-radius: 1rem;
    box-shadow: 0 1rem 2.7rem rgba(26, 62, 52, .09);
}
div[data-testid="stForm"] button[kind="primaryFormSubmit"] {
    min-height: 2.7rem;
    color: white;
    background: var(--mv-green);
    border: 0;
}
.mv-trust {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: .75rem;
    margin: 1.2rem 0 4.5rem;
}
.mv-trust div {
    padding: 1rem;
    color: #4f625b;
    background: #f7faf8;
    border: 1px solid #e8efec;
    border-radius: .85rem;
    font-size: .83rem;
    font-weight: 650;
}
.mv-trust b {
    display: inline-grid;
    place-items: center;
    width: 1.35rem;
    height: 1.35rem;
    margin-right: .45rem;
    color: #12645b;
    background: #e2f1ec;
    border-radius: 50%;
}
.mv-section-title {
    max-width: 42rem;
    margin: 0 auto 2rem;
    text-align: center;
}
.mv-section-title small {
    color: #12645b;
    font-weight: 800;
    letter-spacing: .08em;
    text-transform: uppercase;
}
    .mv-section-title h2 {
        margin: .65rem 0;
        color: var(--mv-ink);
        font-size: clamp(2rem, 4vw, 3.2rem);
        line-height: 1.08;
        letter-spacing: -.045em;
    }
    .mv-how-section {
        position: relative;
        margin: 6.5rem 0;
        padding: clamp(2.5rem, 5vw, 4.5rem);
        overflow: hidden;
        background:
            radial-gradient(circle at 10% 15%, rgba(241,196,91,.16), transparent 26%),
            linear-gradient(145deg, #0b514b, #073f3b);
        border: 1px solid rgba(255,255,255,.08);
        border-radius: 1.8rem;
        box-shadow: 0 1.8rem 4.5rem rgba(7,63,59,.16);
    }
    .mv-how-section::after {
        content: "";
        position: absolute;
        width: 18rem;
        height: 18rem;
        right: -8rem;
        bottom: -10rem;
        border: 1px solid rgba(255,255,255,.08);
        border-radius: 50%;
        box-shadow:
            0 0 0 3rem rgba(255,255,255,.025),
            0 0 0 6rem rgba(255,255,255,.018);
    }
    .mv-how-section .mv-section-title {
        position: relative;
        z-index: 1;
        max-width: 31rem;
        margin: 0;
        text-align: left;
    }
    .mv-how-section .mv-section-title small {
        display: inline-flex;
        align-items: center;
        gap: .55rem;
        padding: .5rem .75rem;
        color: #f6d47d;
        background: rgba(255,255,255,.08);
        border: 1px solid rgba(255,255,255,.12);
        border-radius: 999px;
        box-shadow: 0 .5rem 1.3rem rgba(26,62,52,.06);
    }
    .mv-how-section .mv-section-title small::before {
        content: "";
        width: .5rem;
        height: .5rem;
        background: #f1c45b;
        border-radius: 50%;
    }
    .mv-how-section .mv-section-title h2 {
        margin-top: 1.2rem;
        color: white;
        font-size: clamp(2.7rem, 4.4vw, 4rem);
    }
    .mv-how-section .mv-section-title h2 em {
        position: relative;
        color: #f1c45b;
        font-style: normal;
        white-space: normal;
    }
    .mv-how-section .mv-section-title h2 em::after {
        content: "";
        position: absolute;
        z-index: -1;
        height: .55rem;
        right: 0;
        bottom: .1rem;
        left: 0;
        background: rgba(255,255,255,.14);
        border-radius: 999px;
    }
    .mv-how-lead {
        max-width: 29rem;
        margin: 1.2rem 0 0;
        color: #c4d8d3;
        font-size: 1rem;
        line-height: 1.7;
    }
    .mv-how-layout {
        position: relative;
        z-index: 1;
        display: grid;
        grid-template-columns: .86fr 1.14fr;
        gap: clamp(3rem, 7vw, 7rem);
        align-items: center;
    }
    .mv-steps {
        display: flex;
        flex-direction: column;
        gap: 1rem;
        margin: 0;
        overflow: visible;
        background: transparent;
        border: 0;
        border-radius: 0;
        box-shadow: none;
    }
    .mv-step {
        position: relative;
        min-height: 0;
        display: grid;
        grid-template-columns: 7.4rem 1fr 2rem;
        gap: 2rem;
        align-items: center;
        padding: 1.8rem 2rem;
        color: #162521;
        background: rgba(255,255,255,.96);
        border: 1px solid rgba(255,255,255,.35);
        border-radius: 1.05rem;
        box-shadow: 0 .9rem 2.2rem rgba(3,43,40,.12);
        transition: background-color .2s ease, transform .2s ease;
    }
    .mv-step + .mv-step {
        border-top: 1px solid rgba(255,255,255,.35);
    }
    .mv-step:hover {
        background: white;
        transform: translateY(-.12rem);
    }
    .mv-step-kicker {
        min-height: 3.2rem;
        display: flex;
        align-items: center;
        padding-right: 1.6rem;
        color: #12645b;
        border-right: 1px solid #dce7e2;
        font-size: 1rem;
        font-weight: 800;
        letter-spacing: -.01em;
        text-transform: none;
    }
    .mv-step h3 {
        margin: 0 0 .5rem;
        color: #142721;
        font-size: 1.12rem;
        letter-spacing: -.015em;
    }
    .mv-step p {
        margin: 0;
        color: #687872;
        font-size: .86rem;
        line-height: 1.65;
    }
    .mv-step-arrow {
        color: #b1c0ba;
        font-size: 1.2rem;
        transition: color .2s ease, transform .2s ease;
    }
    .mv-step:hover .mv-step-arrow {
        color: #12645b;
        transform: translateX(.2rem);
    }
.mv-regions {
    display: grid;
    grid-template-columns: 1.05fr .95fr;
    gap: 2rem;
    align-items: center;
    margin: 1rem 0 3rem;
    padding: 2.5rem;
    color: white;
    background: var(--mv-green-dark);
    border-radius: 1.4rem;
}
.mv-regions h2 {
    margin: .5rem 0 1rem;
    font-size: clamp(2rem, 3.5vw, 3.2rem);
    line-height: 1.08;
    letter-spacing: -.045em;
}
.mv-regions p {
    color: #bdd0cb;
    line-height: 1.65;
}
.mv-city-list {
    display: flex;
    flex-wrap: wrap;
    gap: .5rem;
}
.mv-city-list span {
    padding: .5rem .65rem;
    color: #d8e6e2;
    background: rgba(255,255,255,.07);
    border: 1px solid rgba(255,255,255,.1);
    border-radius: .5rem;
    font-size: .72rem;
}
.mv-region-stats {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: .7rem;
}
.mv-region-stats div {
    min-height: 7.5rem;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 1.2rem;
    background: rgba(255,255,255,.07);
    border: 1px solid rgba(255,255,255,.1);
    border-radius: .8rem;
}
.mv-region-stats b {
    color: var(--mv-yellow);
    font-size: 1.7rem;
}
.mv-region-stats span {
    color: #c3d6d1;
    font-size: .72rem;
}
@media (max-width: 800px) {
    .mv-hero {
        grid-template-columns: 1fr;
        gap: 2rem;
        min-height: auto;
        padding: 2.2rem 1.25rem;
    }
    .mv-hero h1 { font-size: clamp(2.6rem, 13vw, 4rem); }
    .mv-map-shell { min-height: 19rem; }
    .mv-map { height: 15.5rem; }
    .mv-trust, .mv-steps, .mv-regions { grid-template-columns: 1fr; }
    .mv-step {
        grid-template-columns: 1fr auto;
        gap: .8rem 1rem;
        padding: 1.6rem 1.25rem;
    }
    .mv-step-kicker {
        min-height: auto;
        grid-column: 1 / -1;
        padding-right: 0;
        padding-bottom: .15rem;
        border-right: 0;
    }
    .mv-step-arrow { grid-column: 2; grid-row: 2; }
    .mv-regions { padding: 1.6rem; }
}
</style>
""", unsafe_allow_html=True)


def renderizar_administracao():
    """Ações que só podem ser exibidas após autenticação administrativa."""
    st.subheader("🔒 Administração")
    st.caption("As alterações de configuração e a atualização manual ficam restritas a administradores.")

    if st.button("🔄 Atualizar agora", key="atualizar_agora", use_container_width=True):
        with st.spinner("Buscando imóveis nos sites configurados..."):
            rodar_agora_async().join()
        st.success("Atualizado!")

    st.divider()
    st.subheader("Adicionar imobiliária por URL")
    st.caption("O sistema abre a página, identifica os cards e cria uma configuração inicial. Use somente URLs de listagem de aluguel autorizadas pela imobiliária.")
    with st.form("nova_imobiliaria"):
        nova_url = st.text_input("URL da página de imóveis para aluguel")
        nova_cidade = st.text_input("Cidade padrão", value="Ipatinga")
        cadastrar = st.form_submit_button("Inspecionar e adicionar", use_container_width=True)

    if cadastrar:
        if not nova_url.strip():
            st.error("Informe a URL da página de listagem.")
        else:
            with st.spinner("Abrindo a imobiliária e identificando os seletores..."):
                nova_deteccao = inspecionar_url(nova_url)
            if nova_deteccao.get("erro"):
                st.error(nova_deteccao["erro"])
            elif nova_deteccao["confianca"] < 0.65:
                st.error("A confiança da detecção foi baixa. Use o envio manual de HTML abaixo para revisar os seletores.")
            else:
                url_final = nova_deteccao["url"]
                host = urlparse(url_final).netloc.removeprefix("www.")
                chave = unicodedata.normalize("NFKD", host.split(".")[0]).encode("ascii", "ignore").decode().lower()
                chave = re.sub(r"[^a-z0-9]+", "_", chave).strip("_") or "nova_imobiliaria"
                config_path = Path(__file__).parent / "sites_config.yaml"
                config_atual = yaml.safe_load(config_path.read_text(encoding="utf-8"))
                chave_base, numero = chave, 2
                while chave in config_atual["sites"]:
                    chave = f"{chave_base}_{numero}"
                    numero += 1
                config_atual["sites"][chave] = {
                    "nome": host,
                    "logo": "",
                    "base_url": f"{urlparse(url_final).scheme}://{urlparse(url_final).netloc}",
                    "listagem_url": url_final,
                    "cidade_padrao": nova_cidade.strip() or "Ipatinga",
                    "espera_seletor": nova_deteccao["seletores"]["card"],
                    "paginacao": {"tipo": "nenhuma"},
                    "seletores": nova_deteccao["seletores"],
                }
                config_path.write_text(yaml.safe_dump(config_atual, allow_unicode=True, sort_keys=False), encoding="utf-8")
                st.success(f"Imobiliária adicionada como '{chave}'. Fazendo a primeira coleta...")
                rodar_site_agora_async(chave).join()
                st.success("Primeira coleta concluída. Atualize a página para ver os imóveis.")

    st.divider()
    st.subheader("Encontrar imobiliárias no Vale do Aço")
    st.caption("Busca sites públicos de aluguel em Ipatinga, Timóteo, Coronel Fabriciano e Santana do Paraíso. No máximo cinco domínios são inspecionados por execução.")
    if st.button("Buscar, inspecionar e cadastrar sites", key="descobrir_vale_aco", use_container_width=True):
        with st.spinner("Procurando e validando imobiliárias da região..."):
            candidatos = descobrir_urls_vale_aco()
            config_path = Path(__file__).parent / "sites_config.yaml"
            config_atual = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            dominios_existentes = {urlparse(site["base_url"]).netloc.removeprefix("www.") for site in config_atual["sites"].values()}
            adicionadas, ignoradas, relatorio = [], [], []
            for candidato in candidatos:
                host = urlparse(candidato["url"]).netloc.removeprefix("www.")
                if host in dominios_existentes:
                    ignoradas.append(host)
                    relatorio.append({"site": host, "resultado": "Já cadastrado"})
                    continue
                deteccao = inspecionar_url(candidato["url"])
                essenciais = {"card", "link", "preco"}
                if deteccao.get("erro"):
                    ignoradas.append(host)
                    relatorio.append({"site": host, "resultado": deteccao["erro"]})
                    continue
                if deteccao.get("confianca", 0) < 0.45 or not essenciais.issubset(deteccao.get("seletores", {})):
                    ignoradas.append(host)
                    relatorio.append({"site": host, "resultado": "Seletores essenciais não foram identificados"})
                    continue
                chave = unicodedata.normalize("NFKD", host.split(".")[0]).encode("ascii", "ignore").decode().lower()
                chave = re.sub(r"[^a-z0-9]+", "_", chave).strip("_") or "nova_imobiliaria"
                chave_base, numero = chave, 2
                while chave in config_atual["sites"]:
                    chave = f"{chave_base}_{numero}"
                    numero += 1
                url_final = deteccao["url"]
                config_atual["sites"][chave] = {
                    "nome": host,
                    "logo": "",
                    "base_url": f"{urlparse(url_final).scheme}://{urlparse(url_final).netloc}",
                    "listagem_url": url_final,
                    "cidade_padrao": candidato["municipio"],
                    "espera_seletor": deteccao["seletores"]["card"],
                    "paginacao": {"tipo": "nenhuma"},
                    "seletores": deteccao["seletores"],
                }
                dominios_existentes.add(host)
                adicionadas.append(chave)
                relatorio.append({"site": host, "resultado": f"Adicionado como {chave}"})
            if adicionadas:
                config_path.write_text(yaml.safe_dump(config_atual, allow_unicode=True, sort_keys=False), encoding="utf-8")
                for chave in adicionadas:
                    rodar_site_agora_async(chave).join()
        if adicionadas:
            st.success(f"Imobiliárias adicionadas e coletadas: {', '.join(adicionadas)}.")
        else:
            st.info("Nenhum site novo passou pela validação automática nesta execução.")
        if ignoradas:
            st.caption("Ignorados (já cadastrados ou sem confiança suficiente): " + ", ".join(ignoradas))
        if relatorio:
            st.dataframe(relatorio, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Detectar seletores")
    st.caption("Envie o HTML renderizado gerado por `inspect_selectors.py`. Revise a sugestão antes de salvar.")
    html_enviado = st.file_uploader("HTML da listagem", type=["html", "htm"], key="html_detector")
    if not html_enviado:
        return

    resultado_detector = detectar_seletores(html_enviado.getvalue().decode("utf-8", errors="replace"))
    if resultado_detector.get("erro"):
        st.error(resultado_detector["erro"])
        return

    st.success(f"{resultado_detector['cards_encontrados']} cards; confiança {resultado_detector['confianca']:.0%}")
    st.caption(f"Plataforma identificada: `{resultado_detector['plataforma']}`" + (" — padrão aprendido aplicado." if resultado_detector["padrao_aprendido"] else ""))
    st.code(yaml.safe_dump(resultado_detector["seletores"], allow_unicode=True, sort_keys=False), language="yaml")
    st.warning(resultado_detector["aviso"])
    config_path = Path(__file__).parent / "sites_config.yaml"
    config_atual = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    site_destino = st.selectbox("Aplicar sugestão ao site", list(config_atual["sites"]), key="site_detector")
    if st.button("Salvar seletores sugeridos", key="salvar_detector", use_container_width=True):
        config_atual["sites"][site_destino]["seletores"].update(resultado_detector["seletores"])
        config_path.write_text(
            yaml.safe_dump(config_atual, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        st.success(f"Seletores salvos para {site_destino} em sites_config.yaml.")

    with st.expander("🧠 Ensinar seletores corretos"):
        st.caption("Corrija os campos que falharam. O padrão será reutilizado automaticamente em sites da mesma plataforma.")
        campos_aprendizagem = {}
        for campo in ("card", "link", "titulo", "preco", "bairro", "thumbnail"):
            campos_aprendizagem[campo] = st.text_input(
                campo, value=resultado_detector["seletores"].get(campo, ""), key=f"aprender_{campo}"
            )
        campos_aprendizagem["thumbnail_attr"] = resultado_detector["seletores"].get("thumbnail_attr", "src")
        if st.button("Salvar correção e ensinar algoritmo", key="ensinar_detector", use_container_width=True):
            if not all(campos_aprendizagem[campo] for campo in ("card", "link", "preco")):
                st.error("Card, link e preço são obrigatórios para ensinar o padrão.")
            else:
                config_atual["sites"][site_destino]["seletores"].update(campos_aprendizagem)
                config_path.write_text(yaml.safe_dump(config_atual, allow_unicode=True, sort_keys=False), encoding="utf-8")
                salvar_padrao(resultado_detector["plataforma"], campos_aprendizagem)
                st.success("Correção salva. As próximas detecções dessa plataforma usarão esse aprendizado.")

def renderizar_landing(cidades):
    """Apresenta o produto e transforma a chamada principal em uma busca real."""
    st.markdown(
        f"""
        <section class="mv-hero">
            <div class="mv-hero-copy">
                <div class="mv-eyebrow">Imóveis de diferentes imobiliárias, em um só lugar</div>
                <h1>Seu próximo lar, em uma busca <em>mais simples.</em></h1>
                <p>
                    Compare casas, apartamentos e kitnets para alugar sem abrir dezenas
                    de sites. Explore as regiões atendidas e encontre opções que combinam
                    com o seu momento.
                </p>
            </div>
            <div class="mv-map-shell" aria-label="Mapa da região">
                <div class="mv-map">
                    <span class="mv-road mv-road-a"></span>
                    <span class="mv-road mv-road-b"></span>
                    <span class="mv-road mv-road-c"></span>
                    <span class="mv-river"></span>
                    <span class="mv-pin mv-pin-a"><span>●</span></span>
                    <span class="mv-pin mv-pin-b"><span>●</span></span>
                    <span class="mv-pin mv-pin-c"><span>●</span></span>
                    <span class="mv-map-label">Vale do Aço</span>
                </div>
            </div>
        </section>
        <div class="mv-search-intro">
            <div class="mv-eyebrow">Comece por aqui</div>
            <h2>Onde você quer morar?</h2>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("busca_landing"):
        coluna_cidade, coluna_tipo, coluna_botao = st.columns([1.2, 1, 0.8], vertical_alignment="bottom")
        with coluna_cidade:
            cidade_inicial = st.selectbox("Cidade", cidades, key="cidade_landing")
        with coluna_tipo:
            tipo_inicial = st.selectbox(
                "Tipo de imóvel",
                ["Todos os tipos", "Apartamento", "Casa", "Kitnet"],
                key="tipo_landing",
            )
        with coluna_botao:
            buscar = st.form_submit_button(
                "Encontrar imóveis →",
                type="primary",
                use_container_width=True,
            )

    if buscar:
        st.session_state["cidades_filtro"] = [cidade_inicial]
        st.session_state["tipos_filtro"] = [] if tipo_inicial == "Todos os tipos" else [tipo_inicial]
        st.rerun()

    st.markdown(
        """
        <div class="mv-trust">
            <div><b>✓</b> Várias imobiliárias em uma busca</div>
            <div><b>✓</b> Filtros rápidos e objetivos</div>
            <div><b>✓</b> Acesso direto ao anúncio original</div>
        </div>

        <section>
            <div class="mv-section-title">
                <small>Simples de verdade</small>
                <h2>Menos procura. Mais chance de encontrar.</h2>
            </div>
            <div class="mv-steps">
                <article class="mv-step">
                    <span>01</span>
                    <h3>Escolha seus filtros</h3>
                    <p>Defina cidade, bairro, tipo de imóvel e a faixa de preço.</p>
                </article>
                <article class="mv-step">
                    <span>02</span>
                    <h3>Compare em um só lugar</h3>
                    <p>Veja ofertas de diferentes imobiliárias em uma lista clara ou no mapa.</p>
                </article>
                <article class="mv-step">
                    <span>03</span>
                    <h3>Fale com a imobiliária</h3>
                    <p>Acesse o anúncio original para confirmar detalhes e agendar uma visita.</p>
                </article>
            </div>
        </section>

        <section class="mv-regions">
            <div>
                <div class="mv-eyebrow">Primeira região atendida</div>
                <h2>Começamos pelo Vale do Aço. E o mapa vai crescer.</h2>
                <p>
                    A primeira região reúne quatro cidades. Novos lugares poderão
                    entrar no mapa sem mudar a simplicidade da busca.
                </p>
                <div class="mv-city-list">
                    <span>Ipatinga</span>
                    <span>Timóteo</span>
                    <span>Coronel Fabriciano</span>
                    <span>Santana do Paraíso</span>
                </div>
            </div>
            <div class="mv-region-stats">
                <div><b>7</b><span>imobiliárias integradas</span></div>
                <div><b>4</b><span>cidades atendidas</span></div>
                <div><b>1</b><span>busca para comparar opções</span></div>
                <div><b>Mapa</b><span>com expansão por regiões</span></div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


st.markdown(
    """
    <style>
    /* A experiência v2 ocupa a página inteira e não reutiliza o chrome antigo. */
    [data-testid="stSidebar"],
    [data-testid="collapsedControl"],
    [data-testid="stHeader"],
    [data-testid="stFooter"],
    .stAppToolbar,
    #MainMenu {
        display: none !important;
    }
    .stMainBlockContainer,
    .block-container {
        width: min(100% - 2rem, 1180px) !important;
        max-width: 1180px !important;
        padding: 0 0 2rem !important;
    }
    .stApp {
        background: #fff;
        overflow-x: hidden;
    }
    .mv-site-header {
        min-height: 4.75rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 2rem;
        background: rgba(255,255,255,.96);
        border-bottom: 1px solid #edf1ef;
    }
    .mv-brand {
        display: inline-flex;
        align-items: center;
        gap: .7rem;
        color: #162521 !important;
        font-size: 1.05rem;
        font-weight: 800;
        letter-spacing: -.025em;
        text-decoration: none !important;
    }
    .mv-brand-mark {
        position: relative;
        width: 2.1rem;
        height: 2.1rem;
        background: #0b4f49;
        border-radius: .7rem .7rem .85rem .85rem;
        transform: rotate(45deg);
    }
    .mv-brand-mark::before {
        content: "";
        position: absolute;
        width: 1rem;
        height: 1rem;
        top: .55rem;
        left: .55rem;
        background: white;
        border-radius: .32rem;
    }
    .mv-brand-mark::after {
        content: "";
        position: absolute;
        z-index: 1;
        width: .3rem;
        height: .68rem;
        right: .55rem;
        bottom: .4rem;
        background: #f1c45b;
        border-radius: 999px;
    }
    .mv-nav {
        display: flex;
        align-items: center;
        gap: 1.8rem;
        color: #3d514a;
        font-size: .86rem;
        font-weight: 650;
    }
    .mv-nav a {
        color: inherit !important;
        text-decoration: none !important;
    }
    .mv-nav .mv-nav-cta {
        padding: .7rem 1rem;
        color: white !important;
        background: #0b4f49;
        border-radius: .7rem;
    }
    .mv-v2-hero {
        margin: 0 calc(50% - 50vw) 0;
        padding: 4.6rem max(1rem, calc((100vw - 1180px) / 2));
        background: linear-gradient(135deg, #fbfdfc 0%, #f2f8f5 55%, #f8f5e9 100%);
        border-radius: 0;
    }
    .mv-v2-hero .mv-hero {
        min-height: 32rem;
        margin: 0;
        padding: 0;
        background: transparent;
        border: 0;
        border-radius: 0;
    }
    .mv-v2-hero .mv-hero::before { display: none; }
    .mv-v2-hero .mv-map-shell { min-height: 25rem; }
    .mv-search-anchor {
        position: relative;
        z-index: 6;
        height: 0;
    }
    .mv-search-callout {
        position: absolute;
        top: -8.9rem;
        left: .9rem;
        display: inline-flex;
        align-items: center;
        gap: .45rem;
        padding: .55rem .8rem;
        color: #3c351f;
        background: #f1c45b;
        border: 3px solid white;
        border-radius: 999px;
        box-shadow: 0 .7rem 1.6rem rgba(84,65,20,.17);
        font-size: .7rem;
        font-weight: 850;
        letter-spacing: .06em;
        text-transform: uppercase;
    }
    .mv-search-callout::before {
        content: "⌖";
        font-size: .9rem;
    }
    .mv-v2-search,
    .st-key-mv_v2_search {
        width: 55%;
        margin-top: -6.1rem;
        position: relative;
        z-index: 5;
    }
    .mv-v2-search div[data-testid="stForm"],
    .st-key-mv_v2_search div[data-testid="stForm"] {
        padding: 1rem;
        background:
            linear-gradient(white, white) padding-box,
            linear-gradient(110deg, #0b4f49, #f1c45b) border-box;
        border: 2px solid transparent;
        border-radius: 1.15rem;
        box-shadow:
            0 1.4rem 3.8rem rgba(26,62,52,.16),
            0 0 0 .35rem rgba(241,196,91,.12);
    }
    .mv-v2-search [data-testid="stSelectbox"] label,
    .st-key-mv_v2_search [data-testid="stSelectbox"] label {
        color: #61716c;
        font-size: .76rem;
    }
    .mv-v2-search .stButton button,
    .mv-v2-search [data-testid="stFormSubmitButton"] button {
        min-height: 3rem;
        color: white;
        background: #0b4f49;
        border: 0;
    }
    .mv-v2-trust {
        display: grid;
        grid-template-columns: repeat(3,1fr);
        gap: 1rem;
        padding: 2rem 0 5rem;
        color: #4f625b;
        font-size: .84rem;
        font-weight: 650;
    }
    .mv-v2-trust div {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: .55rem;
    }
    .mv-v2-trust b {
        width: 1.4rem;
        height: 1.4rem;
        display: grid;
        place-items: center;
        color: #12645b;
        background: #eef7f3;
        border-radius: 50%;
    }
    .mv-showcase {
        padding: 6.5rem 0;
    }
    .mv-category-section {
        position: relative;
        margin: 6.5rem 0;
        padding: clamp(2rem, 5vw, 4rem);
        overflow: hidden;
        color: white;
        background:
            radial-gradient(circle at 8% 15%, rgba(241,196,91,.14), transparent 25%),
            #073f3b;
        border-radius: 1.8rem;
        box-shadow: 0 1.8rem 4.5rem rgba(7,63,59,.16);
    }
    .mv-category-section::after {
        content: "";
        position: absolute;
        width: 18rem;
        height: 18rem;
        right: -9rem;
        top: -10rem;
        border: 1px solid rgba(255,255,255,.08);
        border-radius: 50%;
        box-shadow: 0 0 0 3rem rgba(255,255,255,.025);
    }
    .mv-category-shell {
        position: relative;
        z-index: 1;
        display: grid;
        grid-template-columns: .8fr 1.2fr;
        gap: clamp(2.5rem, 6vw, 6rem);
        align-items: center;
    }
    .mv-category-intro .mv-eyebrow { color: #bdd5cf; }
    .mv-category-intro h2 {
        margin: 0 0 1.2rem;
        color: white;
        font-size: clamp(2.5rem, 4.2vw, 4rem);
        line-height: 1.06;
        letter-spacing: -.05em;
    }
    .mv-category-intro h2 em {
        color: #f1c45b;
        font-style: normal;
    }
    .mv-category-intro p {
        max-width: 28rem;
        margin: 0;
        color: #bfd2cd;
        line-height: 1.7;
    }
    .mv-category-list {
        display: flex;
        flex-direction: column;
        gap: .75rem;
    }
    .mv-category-link {
        display: grid;
        grid-template-columns: auto 1fr auto;
        gap: 1rem;
        align-items: center;
        padding: 1rem 1.1rem;
        color: white !important;
        background: rgba(255,255,255,.075);
        border: 1px solid rgba(255,255,255,.11);
        border-radius: 1rem;
        text-decoration: none !important;
        transition: transform .2s, background .2s, border-color .2s;
    }
    .mv-category-link:hover {
        background: rgba(255,255,255,.13);
        border-color: rgba(241,196,91,.5);
        transform: translateX(.35rem);
    }
    .mv-category-code {
        width: 3.3rem;
        height: 3.3rem;
        display: grid;
        place-items: center;
        color: #073f3b;
        background: #f1c45b;
        border-radius: .9rem;
        font-size: .72rem;
        font-weight: 900;
        letter-spacing: .08em;
    }
    .mv-category-text strong,
    .mv-category-text span {
        display: block;
    }
    .mv-category-text strong {
        margin-bottom: .2rem;
        font-size: 1.02rem;
    }
    .mv-category-text span {
        color: #bcd0cb;
        font-size: .76rem;
        line-height: 1.45;
    }
    .mv-category-arrow {
        width: 2.15rem;
        height: 2.15rem;
        display: grid;
        place-items: center;
        color: #073f3b;
        background: white;
        border-radius: 50%;
        font-weight: 800;
    }
    .mv-showcase-head {
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        gap: 4rem;
        margin-bottom: 2.5rem;
    }
    .mv-showcase-copy {
        max-width: 42rem;
    }
    .mv-showcase-head h2,
    .mv-results-title h1 {
        margin: .55rem 0 0;
        color: #162521;
        font-size: clamp(2.35rem,4vw,3.6rem);
        line-height: 1.07;
        letter-spacing: -.05em;
    }
    .mv-showcase-head h2 em {
        color: #12645b;
        font-style: normal;
    }
    .mv-showcase-lead {
        max-width: 28rem;
        margin: 0 0 .25rem;
        color: #61716c;
        line-height: 1.65;
    }
    .mv-preview-grid {
        display: grid;
        grid-template-columns: 1.08fr .92fr;
        grid-template-rows: repeat(2, 1fr);
        gap: 1.25rem;
    }
    .mv-preview-card,
    .mv-result-card {
        overflow: hidden;
        color: #162521 !important;
        background: white;
        border: 1px solid #dce5e1;
        border-radius: 1.1rem;
        text-decoration: none !important;
        transition: transform .2s, box-shadow .2s;
    }
    .mv-preview-card:hover,
    .mv-result-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 1.4rem 3.5rem rgba(26,62,52,.12);
    }
    .mv-property-art {
        position: relative;
        height: 13.5rem;
        overflow: hidden;
        background: linear-gradient(#a8cdca 0 58%, #77977c 58%);
    }
    .mv-property-art.house { background: linear-gradient(#c7dfe0 0 60%, #8dab75 60%); }
    .mv-property-art.studio { background: linear-gradient(135deg,#d7c5ae,#f2eadf 62%,#ad8968); }
    .mv-property-art::before,
    .mv-property-art::after {
        content: "";
        position: absolute;
        bottom: 0;
        background: #e7ddd0;
        box-shadow: inset -1rem 0 rgba(0,0,0,.06);
    }
    .mv-property-art::before {
        width: 28%;
        height: 68%;
        left: 20%;
    }
    .mv-property-art::after {
        width: 25%;
        height: 52%;
        left: 50%;
        background: #c7bbaa;
    }
    .mv-property-art.has-image::before,
    .mv-property-art.has-image::after {
        display: none;
    }
    .mv-property-art.house::before {
        width: 58%;
        height: 45%;
        left: 21%;
        background: #f1e1d1;
    }
    .mv-property-art.house::after {
        width: 42%;
        height: 42%;
        left: 29%;
        bottom: 30%;
        background: #a86f50;
        transform: rotate(45deg);
        z-index: 0;
    }
    .mv-property-art.studio::before {
        width: 58%;
        height: 30%;
        left: 10%;
        bottom: 12%;
        background: #71897e;
        border-radius: .5rem;
    }
    .mv-property-art.studio::after {
        width: 32%;
        height: 58%;
        left: 60%;
        bottom: 24%;
        background: #c8dcde;
        border: .55rem solid #f5eee6;
    }
    .mv-property-badge {
        position: absolute;
        z-index: 2;
        top: .8rem;
        left: .8rem;
        padding: .38rem .55rem;
        color: white;
        background: rgba(8,49,45,.82);
        border-radius: .45rem;
        font-size: .64rem;
        font-weight: 750;
    }
    .mv-preview-body,
    .mv-result-body { padding: 1.2rem; }
    .mv-generic-card {
        min-height: 0;
        display: flex;
        flex-direction: column;
        padding: 1.5rem;
        background: linear-gradient(145deg, #fbfdfc, #f4f8f6);
    }
    .mv-generic-card:first-child {
        grid-row: 1 / 3;
        min-height: 27rem;
        justify-content: space-between;
        background:
            radial-gradient(circle at 75% 20%, rgba(241,196,91,.14), transparent 25%),
            linear-gradient(145deg, #f8fbfa, #eaf4f0);
    }
    .mv-generic-card:nth-child(2) {
        display: grid;
        grid-template-columns: 9.5rem 1fr;
        align-items: center;
        gap: 1.1rem;
        background: #0b4f49;
        border-color: #0b4f49;
        color: white !important;
    }
    .mv-generic-card:nth-child(3) {
        display: grid;
        grid-template-columns: 9.5rem 1fr;
        align-items: center;
        gap: 1.1rem;
        background: #faf7ef;
        border-color: #ebe5d8;
    }
    .mv-generic-visual {
        position: relative;
        height: 10rem;
        display: grid;
        place-items: center;
        overflow: hidden;
        background: #e4f0ec;
        border-radius: .9rem;
    }
    .mv-generic-card:first-child .mv-generic-visual {
        height: 16rem;
    }
    .mv-generic-card:nth-child(2) .mv-generic-visual,
    .mv-generic-card:nth-child(3) .mv-generic-visual {
        height: 100%;
        min-height: 9rem;
    }
    .mv-generic-card:nth-child(2) .mv-generic-visual {
        background: rgba(255,255,255,.1);
    }
    .mv-generic-visual::before,
    .mv-generic-visual::after {
        content: "";
        position: absolute;
        border: 1px solid rgba(11,79,73,.12);
        border-radius: 50%;
    }
    .mv-generic-visual::before {
        width: 9rem;
        height: 9rem;
    }
    .mv-generic-visual::after {
        width: 6rem;
        height: 6rem;
    }
    .mv-generic-card:nth-child(2) .mv-generic-visual::before,
    .mv-generic-card:nth-child(2) .mv-generic-visual::after {
        border-color: rgba(255,255,255,.12);
    }
    .mv-generic-icon {
        position: relative;
        z-index: 1;
        width: 4.2rem;
        height: 4.2rem;
        display: grid;
        place-items: center;
        color: #0b4f49;
        background: white;
        border-radius: 1.15rem;
        box-shadow: 0 .8rem 2rem rgba(26,62,52,.1);
        font-size: .78rem;
        font-weight: 850;
        letter-spacing: .08em;
    }
    .mv-generic-card:nth-child(2) .mv-generic-icon {
        color: #073f3b;
        background: #f1c45b;
    }
    .mv-generic-body {
        padding: 1.25rem .2rem 0;
    }
    .mv-generic-card:nth-child(2) .mv-generic-body,
    .mv-generic-card:nth-child(3) .mv-generic-body {
        padding: 0;
    }
    .mv-generic-body small {
        color: #12645b;
        font-size: .68rem;
        font-weight: 800;
        letter-spacing: .07em;
        text-transform: uppercase;
    }
    .mv-generic-card:nth-child(2) .mv-generic-body small { color: #f1c45b; }
    .mv-generic-body h3 {
        margin: .55rem 0;
        font-size: 1.2rem;
    }
    .mv-generic-body p {
        margin: 0;
        color: #61716c;
        font-size: .84rem;
        line-height: 1.6;
    }
    .mv-generic-card:nth-child(2) .mv-generic-body p { color: #c7dad5; }
    .mv-property-location {
        margin: 0 0 .4rem;
        color: #12645b;
        font-size: .73rem;
        font-weight: 750;
    }
    .mv-preview-body h3,
    .mv-result-body h3 {
        margin: 0 0 .8rem;
        font-size: 1.02rem;
        line-height: 1.35;
    }
    .mv-property-meta {
        min-height: 2rem;
        color: #61716c;
        font-size: .72rem;
    }
    .mv-property-price {
        margin-top: .85rem;
        padding-top: .85rem;
        border-top: 1px solid #e3e9e6;
        font-size: .72rem;
    }
    .mv-property-price b { font-size: 1.18rem; }
    .mv-footer {
        margin: 4rem calc(50% - 50vw) -2rem;
        padding: 3rem max(1rem, calc((100vw - 1180px) / 2));
        color: #aabbb6;
        background: #092f2c;
    }
    .mv-footer-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 2rem;
    }
    .mv-footer .mv-brand { color: white !important; }
    .mv-footer p { margin: .8rem 0 0; font-size: .76rem; }
    .mv-results-hero {
        margin: 0 calc(50% - 50vw);
        padding: 3.8rem max(1rem, calc((100vw - 1180px) / 2)) 5rem;
        background: linear-gradient(135deg,#f5faf8,#faf6e9);
    }
    .mv-results-title p {
        max-width: 42rem;
        margin: 1rem 0 0;
        color: #61716c;
        line-height: 1.65;
    }
    .mv-filter-shell,
    .st-key-mv_filter_shell {
        position: relative;
        z-index: 4;
        margin-top: -2rem;
        padding: 1.1rem;
        background: white;
        border: 1px solid #dce5e1;
        border-radius: 1.1rem;
        box-shadow: 0 1.3rem 3.4rem rgba(26,62,52,.1);
    }
    .st-key-mv_v2_search [data-testid="stSelectbox"] [data-baseweb="select"],
    .st-key-mv_filter_shell [data-testid="stSelectbox"] [data-baseweb="select"],
    .st-key-mv_filter_shell [data-testid="stMultiSelect"] [data-baseweb="select"] {
        padding: 1.5px;
        background: linear-gradient(110deg, #0b4f49, #2f786e 48%, #f1c45b) !important;
        border-radius: .65rem !important;
        transition: box-shadow .2s ease, background .2s ease;
    }
    .st-key-mv_v2_search [data-testid="stSelectbox"] [data-baseweb="select"] > div,
    .st-key-mv_filter_shell [data-testid="stSelectbox"] [data-baseweb="select"] > div,
    .st-key-mv_filter_shell [data-testid="stMultiSelect"] [data-baseweb="select"] > div {
        background: #f8fbf9 !important;
        border: 0 !important;
        border-radius: calc(.65rem - 1.5px) !important;
    }
    .st-key-mv_v2_search [data-testid="stSelectbox"]:focus-within [data-baseweb="select"] > div,
    .st-key-mv_filter_shell [data-testid="stSelectbox"]:focus-within [data-baseweb="select"] > div,
    .st-key-mv_filter_shell [data-testid="stMultiSelect"]:focus-within [data-baseweb="select"] > div {
        background: white !important;
    }
    .st-key-mv_v2_search [data-testid="stSelectbox"]:focus-within [data-baseweb="select"],
    .st-key-mv_filter_shell [data-testid="stSelectbox"]:focus-within [data-baseweb="select"],
    .st-key-mv_filter_shell [data-testid="stMultiSelect"]:focus-within [data-baseweb="select"] {
        box-shadow: 0 0 0 .22rem rgba(241,196,91,.14) !important;
    }
    .st-key-mv_filter_shell [data-testid="stSlider"] {
        padding: .7rem .85rem .45rem;
        background:
            linear-gradient(white, white) padding-box,
            linear-gradient(110deg, #0b4f49, #2f786e 48%, #f1c45b) border-box;
        border: 1.5px solid transparent;
        border-radius: .65rem;
    }
    [data-testid="stSelectbox"] div[data-baseweb="select"],
    [data-testid="stMultiSelect"] div[data-baseweb="select"] {
        box-sizing: border-box;
        min-height: 40px;
        padding: 2px !important;
        background: linear-gradient(110deg, #07534b 0%, #168072 48%, #f1c45b 100%) !important;
        border: 0 !important;
        border-radius: .72rem !important;
    }
    [data-testid="stSelectbox"] div[data-baseweb="select"] > div,
    [data-testid="stMultiSelect"] div[data-baseweb="select"] > div {
        min-height: 36px;
        align-items: center;
        background: #f3f7f5 !important;
        border: 0 !important;
        border-radius: .58rem !important;
    }
    [data-testid="stSelectbox"]:focus-within div[data-baseweb="select"],
    [data-testid="stMultiSelect"]:focus-within div[data-baseweb="select"] {
        background: linear-gradient(110deg, #07534b 0%, #f1c45b 100%) !important;
        box-shadow: 0 0 0 .24rem rgba(241,196,91,.18) !important;
    }
    [data-testid="stSelectbox"] .react-aria-ComboBox > div:has(input[role="combobox"]) {
        box-sizing: border-box;
        background:
            linear-gradient(#f3f7f5, #f3f7f5) padding-box,
            linear-gradient(110deg, #07534b 0%, #168072 48%, #f1c45b 100%) border-box !important;
        border: 2px solid transparent !important;
        border-radius: .72rem !important;
        transition: box-shadow .2s ease, background .2s ease;
    }
    [data-testid="stSelectbox"] .react-aria-ComboBox:focus-within > div:has(input[role="combobox"]) {
        background:
            linear-gradient(white, white) padding-box,
            linear-gradient(110deg, #07534b 0%, #f1c45b 100%) border-box !important;
        box-shadow: 0 0 0 .24rem rgba(241,196,91,.18) !important;
    }
    [data-testid="stSlider"] {
        box-sizing: border-box;
        padding: .7rem .85rem .45rem;
        background:
            linear-gradient(white, white) padding-box,
            linear-gradient(110deg, #07534b 0%, #168072 48%, #f1c45b 100%) border-box;
        border: 2px solid transparent;
        border-radius: .72rem;
    }
    .mv-result-summary {
        display: flex;
        align-items: end;
        justify-content: space-between;
        gap: 2rem;
        margin: 4rem 0 1.5rem;
    }
    .mv-result-summary h2 {
        margin: 0 0 .3rem;
        font-size: 2rem;
        letter-spacing: -.04em;
    }
    .mv-result-summary p { margin: 0; color: #61716c; }
    .st-key-mv_pagination {
        margin: 2.5rem auto 1rem;
        padding: .8rem;
        background: #f7faf8;
        border: 1px solid #e1e9e5;
        border-radius: 1rem;
    }
    .st-key-mv_pagination p {
        margin: .65rem 0 0;
        color: #53655f;
        font-size: .86rem;
        font-weight: 700;
        text-align: center;
    }
    .st-key-mv_pagination button {
        min-height: 2.8rem;
        color: #0b4f49;
        background: white;
        border: 1px solid #cddbd6;
    }
    .st-key-mv_pagination button:hover:not(:disabled) {
        color: white;
        background: #0b4f49;
        border-color: #0b4f49;
    }
    .mv-empty {
        margin: 2rem 0;
        padding: 4rem 2rem;
        text-align: center;
        background: #f7faf8;
        border: 1px solid #e1e9e5;
        border-radius: 1.2rem;
    }
    .mv-empty h3 { margin: 0 0 .6rem; font-size: 1.4rem; }
    .mv-empty p { max-width: 34rem; margin: 0 auto; color: #61716c; }
    [data-testid="stTabs"] button[role="tab"] { font-weight: 700; }
    .stLinkButton a {
        color: white !important;
        background: #0b4f49 !important;
        border: 0 !important;
    }
    .mv-admin-shell {
        max-width: 52rem;
        margin: 3rem auto;
        padding: 2rem;
        background: white;
        border: 1px solid #dce5e1;
        border-radius: 1.2rem;
        box-shadow: 0 1.4rem 3.5rem rgba(26,62,52,.1);
    }
    @media (max-width: 800px) {
        .stMainBlockContainer,
        .block-container { width: min(100% - 1rem,1180px) !important; }
        .mv-site-header { min-height: 4.25rem; }
        .mv-nav a:not(.mv-nav-cta) { display: none; }
        .mv-v2-hero { padding-top: 2.8rem; padding-bottom: 4rem; }
        .mv-v2-hero .mv-hero { grid-template-columns: 1fr; }
        .mv-v2-hero .mv-map-shell { min-height: 19rem; }
        .mv-v2-search,
        .st-key-mv_v2_search {
            width: 100%;
            margin-top: 4rem;
        }
        .mv-search-callout {
            top: .7rem;
            left: .4rem;
        }
        .mv-v2-trust,
        .mv-preview-grid { grid-template-columns: 1fr; }
        .mv-how-section {
            margin: 4.5rem 0;
            padding: 3rem 1.25rem;
            border-radius: 1.4rem;
        }
        .mv-how-layout { grid-template-columns: 1fr; gap: 2.5rem; }
        .mv-how-section .mv-section-title { max-width: 38rem; }
        .mv-how-section .mv-section-title h2 em { white-space: normal; }
        .mv-v2-trust div { justify-content: flex-start; }
        .mv-category-section { margin: 4.5rem 0; padding: 2rem 1.2rem; }
        .mv-category-shell { grid-template-columns: 1fr; gap: 2rem; }
        .mv-category-link { grid-template-columns: auto 1fr auto; }
        .mv-showcase-head,
        .mv-result-summary,
        .mv-footer-row { display: block; }
        .mv-showcase-lead { margin-top: 1.2rem; }
        .mv-preview-card { max-width: 32rem; margin-inline: auto; }
        .mv-generic-card:first-child {
            grid-row: auto;
            min-height: 22rem;
        }
        .mv-generic-card:nth-child(2),
        .mv-generic-card:nth-child(3) {
            display: flex;
            min-height: 20rem;
        }
        .mv-generic-card:nth-child(2) .mv-generic-visual,
        .mv-generic-card:nth-child(3) .mv-generic-visual {
            width: 100%;
            height: 10rem;
            min-height: 10rem;
        }
        .mv-generic-card:nth-child(2) .mv-generic-body,
        .mv-generic-card:nth-child(3) .mv-generic-body {
            padding: 1.25rem .2rem 0;
        }
        .mv-results-hero { padding-top: 2.7rem; padding-bottom: 4.5rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def renderizar_header_v2(tela="inicio"):
    if tela == "resultados":
        links = """
            <a href="?tela=inicio" target="_self">Nova busca</a>
            <a class="mv-nav-cta" href="?tela=admin" target="_self">Administração</a>
        """
    elif tela == "admin":
        links = """
            <a href="?tela=inicio" target="_self">Página inicial</a>
            <a class="mv-nav-cta" href="?tela=resultados" target="_self">Ver imóveis</a>
        """
    else:
        links = """
            <a href="#como-funciona">Como funciona</a>
            <a href="#imoveis">Imóveis</a>
            <a href="#regioes">Onde estamos</a>
            <a class="mv-nav-cta" href="#buscar">Buscar imóveis</a>
        """
    st.markdown(
        f"""
        <header class="mv-site-header">
            <a class="mv-brand" href="?tela=inicio" target="_self">
                <span class="mv-brand-mark"></span>
                <span>Mapa do Aluguel</span>
            </a>
            <nav class="mv-nav" aria-label="Navegação principal">{links}</nav>
        </header>
        """,
        unsafe_allow_html=True,
    )


def renderizar_footer_v2():
    st.markdown(
        """
        <footer class="mv-footer">
            <div class="mv-footer-row">
                <div>
                    <a class="mv-brand" href="?tela=inicio" target="_self">
                        <span class="mv-brand-mark"></span>
                        <span>Mapa do Aluguel</span>
                    </a>
                    <p>Um jeito simples de encontrar imóveis para alugar nas regiões atendidas.</p>
                </div>
                <p>© 2026 Mapa do Aluguel</p>
            </div>
        </footer>
        """,
        unsafe_allow_html=True,
    )


def obter_contexto_regional():
    """Resolve no navegador a região atendida mais próxima, sem enviar coordenadas."""
    regiao_slug = st.query_params.get("geo_regiao")
    if not regiao_slug:
        components.html(
            """
            <script>
            (() => {
              const parentUrl = new URL(window.parent.location.href);
              if (parentUrl.searchParams.has("geo_regiao")) return;

              const finish = (region) => {
                parentUrl.searchParams.set("geo_regiao", region);
                window.parent.location.replace(parentUrl.toString());
              };

              if (!navigator.geolocation) {
                finish("indisponivel");
                return;
              }

              navigator.geolocation.getCurrentPosition(
                ({ coords }) => {
                  const supportedRegions = [
                    { slug: "vale-aco", lat: -19.47, lon: -42.54, radiusKm: 180 }
                  ];
                  const toRad = (value) => value * Math.PI / 180;
                  const distanceKm = (aLat, aLon, bLat, bLon) => {
                    const earthRadius = 6371;
                    const dLat = toRad(bLat - aLat);
                    const dLon = toRad(bLon - aLon);
                    const value =
                      Math.sin(dLat / 2) ** 2 +
                      Math.cos(toRad(aLat)) * Math.cos(toRad(bLat)) *
                      Math.sin(dLon / 2) ** 2;
                    return 2 * earthRadius * Math.asin(Math.sqrt(value));
                  };
                  const nearest = supportedRegions
                    .map((region) => ({
                      ...region,
                      distance: distanceKm(
                        coords.latitude,
                        coords.longitude,
                        region.lat,
                        region.lon
                      )
                    }))
                    .sort((a, b) => a.distance - b.distance)[0];
                  finish(nearest && nearest.distance <= nearest.radiusKm ? nearest.slug : "fora-cobertura");
                },
                () => finish("indisponivel"),
                { enableHighAccuracy: false, timeout: 8000, maximumAge: 3600000 }
              );
            })();
            </script>
            """,
            height=0,
        )

    if regiao_slug == "vale-aco":
        return {
            "nome": "Vale do Aço",
            "titulo": "O Vale do Aço está no mapa.",
            "texto": "Encontramos a região atendida mais próxima de você.",
            "cidades": ["Ipatinga", "Timóteo", "Coronel Fabriciano", "Santana do Paraíso"],
        }
    if regiao_slug == "fora-cobertura":
        return {
            "nome": "Em breve por aqui",
            "titulo": "Sua região ainda não está no mapa.",
            "texto": "Estamos começando pelo Vale do Aço e preparando a expansão para novas regiões.",
            "cidades": ["Primeira região: Vale do Aço"],
        }
    return {
        "nome": "Vale do Aço",
        "titulo": "Começamos pelo Vale do Aço. E o mapa vai crescer.",
        "texto": "Permita o acesso à localização para vermos se já atendemos a sua região.",
        "cidades": ["Ipatinga", "Timóteo", "Coronel Fabriciano", "Santana do Paraíso"],
    }


def renderizar_landing_v2():
    renderizar_header_v2("inicio")
    contexto_regional = obter_contexto_regional()
    nome_regiao = html.escape(contexto_regional["nome"])
    titulo_regiao = html.escape(contexto_regional["titulo"])
    texto_regiao = html.escape(contexto_regional["texto"])
    cidades_regiao = "".join(
        f"<span>{html.escape(cidade)}</span>" for cidade in contexto_regional["cidades"]
    )
    st.markdown(
        f"""
        <div class="mv-v2-hero">
            <section class="mv-hero">
                <div class="mv-hero-copy">
                    <div class="mv-eyebrow">Imóveis de diferentes imobiliárias, em um só lugar</div>
                    <h1>Seu próximo lar, em uma busca <em>mais simples.</em></h1>
                    <p>
                        Compare casas, apartamentos e kitnets para alugar sem abrir dezenas
                        de sites. Explore as regiões atendidas e encontre opções que combinam
                        com o seu momento.
                    </p>
                </div>
                <div class="mv-map-shell" aria-label="Mapa da região">
                    <div class="mv-map">
                        <span class="mv-road mv-road-a"></span>
                        <span class="mv-road mv-road-b"></span>
                        <span class="mv-road mv-road-c"></span>
                        <span class="mv-river"></span>
                        <span class="mv-pin mv-pin-a"><span>●</span></span>
                        <span class="mv-pin mv-pin-b"><span>●</span></span>
                        <span class="mv-pin mv-pin-c"><span>●</span></span>
                        <span class="mv-map-label">{nome_regiao}</span>
                    </div>
                </div>
            </section>
        </div>
        <div id="buscar" class="mv-search-anchor">
            <span class="mv-search-callout">Encontre seu imóvel aqui</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    cidades_base = ["Ipatinga", "Timóteo", "Coronel Fabriciano", "Santana do Paraíso"]
    cidades = list(dict.fromkeys(db.listar_cidades() + cidades_base))
    with st.container(key="mv_v2_search"):
        with st.form("busca_landing_v2"):
            coluna_cidade, coluna_tipo, coluna_botao = st.columns([1.2, 1, .85], vertical_alignment="bottom")
            with coluna_cidade:
                cidade = st.selectbox("Cidade", cidades, key="cidade_landing_v2")
            with coluna_tipo:
                tipo = st.selectbox(
                    "Tipo de imóvel",
                    ["Todos os tipos", "Apartamento", "Casa", "Kitnet"],
                    key="tipo_landing_v2",
                )
            with coluna_botao:
                buscar = st.form_submit_button("Encontrar imóveis →", type="primary", use_container_width=True)

    if buscar:
        st.session_state["cidade_resultados"] = cidade
        st.session_state["tipo_resultados"] = tipo
        st.query_params["tela"] = "resultados"
        st.query_params["cidade"] = cidade
        st.query_params["tipo"] = tipo
        st.rerun()

    st.markdown(
        f"""
        <div class="mv-v2-trust">
            <div><b>✓</b> Várias imobiliárias em uma busca</div>
            <div><b>✓</b> Filtros rápidos e objetivos</div>
            <div><b>✓</b> Acesso direto ao anúncio original</div>
        </div>
        <section id="como-funciona" class="mv-how-section">
            <div class="mv-how-layout">
                <div class="mv-section-title">
                    <small>Simples de verdade</small>
                    <h2>Menos procura.<br><em>Mais chance de encontrar.</em></h2>
                    <p class="mv-how-lead">
                        Uma jornada direta, da primeira busca ao contato com a imobiliária,
                        sem repetir filtros em vários sites.
                    </p>
                </div>
                <div class="mv-steps">
                    <article class="mv-step">
                        <div class="mv-step-kicker">Busque</div>
                        <div class="mv-step-copy">
                            <h3>Escolha seus filtros</h3>
                            <p>Defina cidade, bairro, tipo de imóvel e a faixa de preço.</p>
                        </div>
                        <span class="mv-step-arrow" aria-hidden="true">→</span>
                    </article>
                    <article class="mv-step">
                        <div class="mv-step-kicker">Compare</div>
                        <div class="mv-step-copy">
                            <h3>Compare em um só lugar</h3>
                            <p>Veja ofertas de diferentes imobiliárias em uma lista clara ou no mapa.</p>
                        </div>
                        <span class="mv-step-arrow" aria-hidden="true">→</span>
                    </article>
                    <article class="mv-step">
                        <div class="mv-step-kicker">Conecte-se</div>
                        <div class="mv-step-copy">
                            <h3>Fale com a imobiliária</h3>
                            <p>Acesse o anúncio original para confirmar detalhes e agendar uma visita.</p>
                        </div>
                        <span class="mv-step-arrow" aria-hidden="true">→</span>
                    </article>
                </div>
            </div>
        </section>
        <section class="mv-category-section" id="imoveis">
            <div class="mv-category-shell">
                <div class="mv-category-intro">
                    <div class="mv-eyebrow">Escolha por tipo</div>
                    <h2>Comece pelo espaço que combina com <em>você.</em></h2>
                    <p>
                        Selecione uma categoria para abrir os resultados já filtrados.
                        Depois, refine por cidade, bairro e faixa de preço.
                    </p>
                </div>
                <div class="mv-category-list">
                    <a class="mv-category-link" href="?tela=resultados&tipo=Apartamento" target="_self">
                        <span class="mv-category-code">AP</span>
                        <span class="mv-category-text">
                            <strong>Apartamentos</strong>
                            <span>Diferentes tamanhos, localizações e configurações.</span>
                        </span>
                        <span class="mv-category-arrow">→</span>
                    </a>
                    <a class="mv-category-link" href="?tela=resultados&tipo=Casa" target="_self">
                        <span class="mv-category-code">CA</span>
                        <span class="mv-category-text">
                            <strong>Casas</strong>
                            <span>Mais espaço para diferentes rotinas e famílias.</span>
                        </span>
                        <span class="mv-category-arrow">→</span>
                    </a>
                    <a class="mv-category-link" href="?tela=resultados&tipo=Kitnet" target="_self">
                        <span class="mv-category-code">ST</span>
                        <span class="mv-category-text">
                            <strong>Kitnets e studios</strong>
                            <span>Praticidade para uma rotina mais compacta.</span>
                        </span>
                        <span class="mv-category-arrow">→</span>
                    </a>
                </div>
            </div>
        </section>
        <section id="regioes" class="mv-regions">
            <div>
                <h2>{titulo_regiao}</h2>
                <p>{texto_regiao}</p>
                <div class="mv-city-list">{cidades_regiao}</div>
            </div>
            <div class="mv-region-stats">
                <div><b>4</b><span>cidades no Vale do Aço</span></div>
                <div><b>1</b><span>região inicial atendida</span></div>
                <div><b>Busca</b><span>única para comparar opções</span></div>
                <div><b>Mapa</b><span>preparado para novas regiões</span></div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    renderizar_footer_v2()


def _preco_formatado(valor):
    if valor is None:
        return "Consultar"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def renderizar_resultados_v2():
    renderizar_header_v2("resultados")
    cidades_base = ["Ipatinga", "Timóteo", "Coronel Fabriciano", "Santana do Paraíso"]
    cidades = list(dict.fromkeys(db.listar_cidades() + cidades_base))
    cidade_parametro = st.query_params.get("cidade")
    tipo_parametro = st.query_params.get("tipo") or st.query_params.get("categoria")
    assinatura_rota = (cidade_parametro, tipo_parametro)
    if st.session_state.get("_assinatura_resultados_v2") != assinatura_rota:
        if cidade_parametro in cidades:
            st.session_state["cidade_resultados"] = cidade_parametro
            st.session_state["filtro_cidade_v2"] = cidade_parametro
        if tipo_parametro in {"Todos os tipos", "Apartamento", "Casa", "Kitnet"}:
            st.session_state["tipo_resultados"] = tipo_parametro
            st.session_state["filtro_tipo_v2"] = tipo_parametro
        st.session_state["_assinatura_resultados_v2"] = assinatura_rota

    cidade_atual = st.session_state.get("cidade_resultados", cidades[0])
    if cidade_atual not in cidades:
        cidade_atual = cidades[0]

    st.markdown(
        f"""
        <section class="mv-results-hero">
            <div class="mv-results-title">
                <div class="mv-eyebrow">Encontre seu próximo endereço</div>
                <h1>Imóveis para alugar em {html.escape(cidade_atual)}.</h1>
                <p>Compare as opções das imobiliárias da região e refine sua busca sem sair desta página.</p>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    with st.container(key="mv_filter_shell"):
        linha_um = st.columns([1.05, 1, 1, 1])
        with linha_um[0]:
            cidade_padrao = (
                {}
                if "filtro_cidade_v2" in st.session_state
                else {"index": cidades.index(cidade_atual)}
            )
            cidade = st.selectbox(
                "Cidade",
                cidades,
                key="filtro_cidade_v2",
                **cidade_padrao,
            )
        bairros = db.listar_bairros(cidades=[cidade])
        with linha_um[1]:
            bairros_selecionados = st.multiselect("Bairro", bairros, key="filtro_bairros_v2")
        tipos_bd = db.listar_tipos(cidades=[cidade], bairros=bairros_selecionados or None)
        tipos = list(dict.fromkeys(["Todos os tipos"] + tipos_bd + ["Apartamento", "Casa", "Kitnet"]))
        tipo_inicial = st.session_state.get("tipo_resultados", "Todos os tipos")
        if tipo_inicial not in tipos:
            tipo_inicial = "Todos os tipos"
        with linha_um[2]:
            tipo_padrao = (
                {}
                if "filtro_tipo_v2" in st.session_state
                else {"index": tipos.index(tipo_inicial)}
            )
            tipo = st.selectbox(
                "Tipo de imóvel",
                tipos,
                key="filtro_tipo_v2",
                **tipo_padrao,
            )
        imobiliarias = db.listar_imobiliarias(cidades=[cidade], bairros=bairros_selecionados or None)
        with linha_um[3]:
            imobiliarias_selecionadas = st.multiselect(
                "Imobiliária",
                imobiliarias,
                key="filtro_imobiliarias_v2",
            )

        preco_min_bd, preco_max_bd = db.faixa_preco()
        preco_maximo = float(max(preco_max_bd, 5000))
        linha_dois = st.columns([2.1, .9])
        with linha_dois[0]:
            faixa = st.slider(
                "Faixa de preço mensal",
                min_value=0.0,
                max_value=preco_maximo,
                value=(0.0, preco_maximo),
                step=50.0,
                key="filtro_preco_v2",
            )
        with linha_dois[1]:
            ordenacao = st.selectbox(
                "Ordenar por",
                ["Mais recentes", "Menor preço", "Maior preço"],
                key="ordenacao_v2",
            )

    st.session_state["cidade_resultados"] = cidade
    st.session_state["tipo_resultados"] = tipo
    st.query_params["cidade"] = cidade
    st.query_params["tipo"] = tipo
    tipos_consulta = None if tipo == "Todos os tipos" else [tipo]
    ordem_banco = {
        "Mais recentes": "recentes",
        "Menor preço": "preco_asc",
        "Maior preço": "preco_desc",
    }[ordenacao]
    assinatura_paginacao = (
        cidade,
        tuple(bairros_selecionados),
        tipo,
        tuple(imobiliarias_selecionadas),
        faixa,
        ordenacao,
    )
    if st.session_state.get("_assinatura_paginacao_v2") != assinatura_paginacao:
        st.session_state["_assinatura_paginacao_v2"] = assinatura_paginacao
        st.session_state["pagina_resultados_v2"] = 1

    itens_por_pagina = 12
    total_imoveis = db.contar_imoveis(
        preco_min=faixa[0],
        preco_max=faixa[1],
        bairros=bairros_selecionados or None,
        cidades=[cidade],
        tipos=tipos_consulta,
        imobiliarias=imobiliarias_selecionadas or None,
    )
    total_paginas = max(1, (total_imoveis + itens_por_pagina - 1) // itens_por_pagina)
    pagina_atual = min(
        max(1, st.session_state.get("pagina_resultados_v2", 1)),
        total_paginas,
    )
    st.session_state["pagina_resultados_v2"] = pagina_atual
    st.query_params["pagina"] = str(pagina_atual)
    imoveis = db.listar_imoveis(
        preco_min=faixa[0],
        preco_max=faixa[1],
        bairros=bairros_selecionados or None,
        cidades=[cidade],
        tipos=tipos_consulta,
        imobiliarias=imobiliarias_selecionadas or None,
        ordenar_por=ordem_banco,
        limite=itens_por_pagina,
        deslocamento=(pagina_atual - 1) * itens_por_pagina,
    )
    primeiro_item = (pagina_atual - 1) * itens_por_pagina + 1 if total_imoveis else 0
    ultimo_item = min(pagina_atual * itens_por_pagina, total_imoveis)

    st.markdown(
        f"""
        <div class="mv-result-summary">
            <div>
                <h2>Imóveis encontrados</h2>
                <p>{total_imoveis} opções em {html.escape(cidade)} · mostrando {primeiro_item}–{ultimo_item}</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    aba_lista, aba_mapa = st.tabs(["Lista de imóveis", "Mapa desta página"])
    with aba_lista:
        if not imoveis:
            st.markdown(
                """
                <div class="mv-empty">
                    <h3>Nenhum imóvel encontrado com estes filtros.</h3>
                    <p>Tente ampliar a faixa de preço ou selecionar outro tipo de imóvel.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            colunas = st.columns(3)
            for indice, imovel in enumerate(imoveis):
                with colunas[indice % 3]:
                    titulo = html.escape(imovel["titulo"] or imovel["imobiliaria"])
                    bairro = html.escape(imovel["bairro"] or "Bairro não informado")
                    cidade_item = html.escape(imovel["cidade"] or cidade)
                    tipo_item = html.escape(imovel.get("tipo") or "Imóvel")
                    imobiliaria = html.escape(imovel["imobiliaria"])
                    thumb = html.escape(imovel["thumbnail_url"] or "", quote=True)
                    imagem_style = (
                        f"background-image:url('{thumb}');background-size:cover;background-position:center;"
                        if thumb else ""
                    )
                    classe_imagem = " has-image" if thumb else ""
                    st.markdown(
                        f"""
                        <article class="mv-result-card">
                            <div class="mv-property-art{classe_imagem}" style="{imagem_style}">
                                <span class="mv-property-badge">{tipo_item}</span>
                            </div>
                            <div class="mv-result-body">
                                <p class="mv-property-location">{bairro} · {cidade_item}</p>
                                <h3>{titulo}</h3>
                                <div class="mv-property-meta">{imobiliaria}</div>
                                <div class="mv-property-price"><b>{_preco_formatado(imovel["preco"])}</b> /mês</div>
                            </div>
                        </article>
                        """,
                        unsafe_allow_html=True,
                    )
                    st.link_button("Ver imóvel →", imovel["url"], use_container_width=True)

    with aba_mapa:
        pontos = [item for item in imoveis if item["latitude"] and item["longitude"]]
        if not pontos:
            st.markdown(
                """
                <div class="mv-empty">
                    <h3>Mapa indisponível para estes resultados.</h3>
                    <p>Os imóveis encontrados ainda não possuem coordenadas cadastradas.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            centro_lat = sum(item["latitude"] for item in pontos) / len(pontos)
            centro_lon = sum(item["longitude"] for item in pontos) / len(pontos)
            mapa = folium.Map(location=[centro_lat, centro_lon], zoom_start=13, tiles="OpenStreetMap")
            cluster = MarkerCluster().add_to(mapa)
            for item in pontos:
                titulo = html.escape(item["titulo"] or item["imobiliaria"])
                bairro = html.escape(item["bairro"] or "")
                url = html.escape(item["url"], quote=True)
                popup = (
                    f"<div style='width:210px'><b>{titulo}</b><br>"
                    f"{_preco_formatado(item['preco'])}/mês<br>{bairro}<br>"
                    f"<a href='{url}' target='_blank'>Ver imóvel</a></div>"
                )
                folium.Marker(
                    [item["latitude"], item["longitude"]],
                    popup=folium.Popup(popup, max_width=250),
                    tooltip=bairro,
                    icon=folium.Icon(color="green", icon="home", prefix="fa"),
                ).add_to(cluster)
            st_folium(mapa, use_container_width=True, height=620)

    if total_paginas > 1:
        with st.container(key="mv_pagination"):
            coluna_anterior, coluna_pagina, coluna_proxima = st.columns([1, 1.4, 1])
            with coluna_anterior:
                if st.button(
                    "← Página anterior",
                    disabled=pagina_atual == 1,
                    use_container_width=True,
                    key="pagina_anterior_v2",
                ):
                    st.session_state["pagina_resultados_v2"] = pagina_atual - 1
                    st.rerun()
            with coluna_pagina:
                st.markdown(f"Página {pagina_atual} de {total_paginas}")
            with coluna_proxima:
                if st.button(
                    "Próxima página →",
                    disabled=pagina_atual == total_paginas,
                    use_container_width=True,
                    key="pagina_proxima_v2",
                ):
                    st.session_state["pagina_resultados_v2"] = pagina_atual + 1
                    st.rerun()
    renderizar_footer_v2()


def renderizar_admin_v2():
    renderizar_header_v2("admin")
    st.markdown('<div class="mv-admin-shell">', unsafe_allow_html=True)
    if "admin_autenticado" not in st.session_state:
        st.session_state.admin_autenticado = False
    try:
        senha_admin = st.secrets["ADMIN_PASSWORD"]
    except Exception:
        senha_admin = None

    if st.session_state.admin_autenticado:
        if st.button("Sair da administração"):
            st.session_state.admin_autenticado = False
            st.rerun()
        renderizar_administracao()
    else:
        st.subheader("Acesso administrativo")
        with st.form("login_admin_v2"):
            tentativa = st.text_input("Senha", type="password")
            entrar = st.form_submit_button("Entrar", type="primary")
        if entrar:
            if senha_admin and hmac.compare_digest(tentativa, senha_admin):
                st.session_state.admin_autenticado = True
                st.rerun()
            elif not senha_admin:
                st.error("Defina ADMIN_PASSWORD nos Secrets do Streamlit.")
            else:
                st.error("Senha incorreta.")
    st.markdown("</div>", unsafe_allow_html=True)
    renderizar_footer_v2()


# A interface anterior permanece abaixo deste ponto e pode ser reativada
# removendo este bloco de roteamento.
tela_atual = st.query_params.get("tela", "inicio")
if tela_atual == "resultados":
    renderizar_resultados_v2()
elif tela_atual == "admin":
    renderizar_admin_v2()
else:
    renderizar_landing_v2()
st.stop()


# -----------------------------------------------------------------------
# Sidebar: autenticação e filtros (interface anterior preservada)
# -----------------------------------------------------------------------
st.sidebar.header("🏠 Mapa do Aluguel")

if "admin_autenticado" not in st.session_state:
    st.session_state.admin_autenticado = False

try:
    senha_admin = st.secrets["ADMIN_PASSWORD"]
except Exception:
    senha_admin = None

if st.session_state.admin_autenticado:
    st.sidebar.success("Acesso administrativo ativo")
    if st.sidebar.button("Sair da administração", use_container_width=True):
        st.session_state.admin_autenticado = False
        st.rerun()
else:
    with st.sidebar.expander("Acesso administrativo"):
        tentativa = st.text_input("Senha", type="password", key="senha_admin")
        if st.button("Entrar", key="entrar_admin", use_container_width=True):
            if senha_admin and hmac.compare_digest(tentativa, senha_admin):
                st.session_state.admin_autenticado = True
                st.rerun()
            elif not senha_admin:
                st.error("Defina ADMIN_PASSWORD nos Secrets do Streamlit.")
            else:
                st.error("Senha incorreta.")

admin_logado = st.session_state.admin_autenticado

st.sidebar.markdown("---")
st.sidebar.subheader("Filtros")

cidades_regiao_inicial = ["Ipatinga", "Timóteo", "Coronel Fabriciano", "Santana do Paraíso"]
cidades_disponiveis = list(dict.fromkeys(db.listar_cidades() + cidades_regiao_inicial))
if "cidades_filtro" not in st.session_state:
    st.session_state["cidades_filtro"] = []
cidades_selecionadas = st.sidebar.multiselect(
    "Cidade *", options=cidades_disponiveis, key="cidades_filtro",
    help="Escolha ao menos uma cidade para ver os imóveis.",
)

if not cidades_selecionadas:
    st.sidebar.info("⬆️ Selecione uma cidade para liberar os demais filtros.")

    if admin_logado:
        aba_inicio, aba_admin = st.tabs(["🏠 Início", "🔒 Administração"])
        with aba_inicio:
            renderizar_landing(cidades_disponiveis)
        with aba_admin:
            renderizar_administracao()
    else:
        renderizar_landing(cidades_disponiveis)
    st.stop()

bairros_disponiveis = db.listar_bairros(cidades=cidades_selecionadas)
bairros_selecionados = st.sidebar.multiselect(
    "Bairro", options=bairros_disponiveis, default=[]
)

tipos_disponiveis = db.listar_tipos(cidades=cidades_selecionadas, bairros=bairros_selecionados or None)
tipos_disponiveis = list(dict.fromkeys(tipos_disponiveis + st.session_state.get("tipos_filtro", [])))
tipos_selecionados = st.sidebar.multiselect(
    "Tipo de imóvel", options=tipos_disponiveis, key="tipos_filtro"
)

imobiliarias_disponiveis = db.listar_imobiliarias(
    cidades=cidades_selecionadas, bairros=bairros_selecionados or None
)
imobiliarias_selecionadas = st.sidebar.multiselect(
    "Imobiliária", options=imobiliarias_disponiveis, default=[]
)

preco_min_bd, preco_max_bd = db.faixa_preco()
if preco_max_bd <= 0:
    preco_max_bd = 5000.0

faixa = st.sidebar.slider(
    "Faixa de preço (R$)",
    min_value=0.0,
    max_value=float(max(preco_max_bd, 1)),
    value=(0.0, float(preco_max_bd)),
    step=50.0,
)

# -----------------------------------------------------------------------
# Busca no banco com os filtros aplicados (ordenação é feita mais abaixo,
# depois que o usuário escolhe a opção na área principal)
# -----------------------------------------------------------------------
imoveis = db.listar_imoveis(
    preco_min=faixa[0],
    preco_max=faixa[1],
    bairros=bairros_selecionados or None,
    cidades=cidades_selecionadas or None,
    tipos=tipos_selecionados or None,
    imobiliarias=imobiliarias_selecionadas or None,
)

st.title("Imóveis disponíveis para alugar")

col_contagem, col_ordenar = st.columns([3, 1])
with col_contagem:
    st.caption(f"{len(imoveis)} imóveis encontrados")
with col_ordenar:
    opcoes_ordenacao = {
        "Mais recentes": "recentes",
        "Menor preço primeiro": "preco_asc",
        "Maior preço primeiro": "preco_desc",
    }
    ordenacao_label = st.selectbox(
        "Ordenar por", options=list(opcoes_ordenacao.keys()), label_visibility="collapsed"
    )
    ordenar_por = opcoes_ordenacao[ordenacao_label]

if ordenar_por == "preco_asc":
    imoveis = sorted(imoveis, key=lambda i: (i["preco"] is None, i["preco"]))
elif ordenar_por == "preco_desc":
    imoveis = sorted(imoveis, key=lambda i: (i["preco"] is None, -(i["preco"] or 0)))

if not imoveis:
    st.info(
        "Nenhum imóvel no banco ainda (ou nenhum bateu com os filtros). "
        "Administradores podem rodar uma atualização pela aba Administração."
    )
    if admin_logado:
        with st.tabs(["🔒 Administração"])[0]:
            renderizar_administracao()
else:
    abas = st.tabs(["📋 Lista de imóveis", "🗺️ Mapa"] + (["🔒 Administração"] if admin_logado else []))
    aba_lista, aba_mapa = abas[:2]

    # ------------------- ABA LISTA (showpage / grid de cards) -------------------
    with aba_lista:
        colunas_por_linha = 3
        colunas = st.columns(colunas_por_linha)
        for i, imovel in enumerate(imoveis):
            col = colunas[i % colunas_por_linha]
            with col:
                thumb_original = imovel["thumbnail_url"] or ""
                # A CDN Imoview abre a foto isolada, mas bloqueia a exibição
                # incorporada no Streamlit em alguns navegadores. Não
                # renderizamos um <img> quebrado: a foto continua disponível
                # ao abrir o anúncio original pelo botão abaixo.
                if thumb_original:
                    st.image(thumb_original, use_container_width=True)
                else:
                    st.caption("Imagem não disponível")
                # A imagem como fundo não produz o ícone quebrado do navegador
                # nem interfere com o HTML interno quando a CDN a bloqueia.
                preco = f"R$ {imovel['preco']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if imovel["preco"] else "Consultar"
                bairro = imovel["bairro"] or "Bairro não informado"
                cidade = html.escape(imovel["cidade"] or "")
                titulo = html.escape(imovel["titulo"] or imovel["imobiliaria"])
                imobiliaria = html.escape(imovel["imobiliaria"])
                tipo_badge_html = f'<div class="card-tipo">{html.escape(imovel["tipo"])}</div>' if imovel.get("tipo") else ""

                st.html(f"""
                <div class="card-imovel">
                    <div class="card-body">
                        {tipo_badge_html}
                        <div class="card-titulo">{titulo}</div>
                        <div class="card-preco">{preco}/mês</div>
                        <div class="card-bairro">{bairro}{', ' + cidade if cidade else ''}</div>
                        <div class="card-imobiliaria">{imobiliaria}</div>
                    </div>
                </div>
                """)
                st.link_button("Ver imóvel", imovel["url"], use_container_width=True)

    # ------------------- ABA MAPA -------------------
    with aba_mapa:
        pontos = [im for im in imoveis if im["latitude"] and im["longitude"]]
        if not pontos:
            st.info("Nenhum imóvel filtrado possui coordenadas geocodificadas ainda.")
        else:
            centro_lat = sum(p["latitude"] for p in pontos) / len(pontos)
            centro_lon = sum(p["longitude"] for p in pontos) / len(pontos)

            mapa = folium.Map(location=[centro_lat, centro_lon], zoom_start=13, tiles="OpenStreetMap")
            cluster = MarkerCluster().add_to(mapa)

            for p in pontos:
                preco_fmt = f"R$ {p['preco']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if p["preco"] else "Consultar"
                popup_html = f"""
                <div style="width:200px">
                    <img src="{p['thumbnail_url'] or ''}" style="width:100%;border-radius:6px;" />
                    <b>{p['titulo'] or p['imobiliaria']}</b><br>
                    {preco_fmt}/mês<br>
                    {p['bairro'] or ''}<br>
                    <i>{p['imobiliaria']}</i><br>
                    <a href="{p['url']}" target="_blank">Ver imóvel</a>
                </div>
                """
                folium.Marker(
                    location=[p["latitude"], p["longitude"]],
                    popup=folium.Popup(popup_html, max_width=250),
                    tooltip=p["bairro"],
                    icon=folium.Icon(color="green", icon="home", prefix="fa"),
                ).add_to(cluster)

            st_folium(mapa, use_container_width=True, height=600)

    if admin_logado:
        with abas[2]:
            renderizar_administracao()
