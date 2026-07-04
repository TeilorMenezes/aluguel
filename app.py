import subprocess
import sys

import streamlit as st
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

import db
from scheduler_runner import iniciar_agendador, rodar_agora_async

st.set_page_config(page_title="Imóveis para Alugar", layout="wide", page_icon="🏠")


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
iniciar_agendador()  # cacheado via variável de módulo (só cria os jobs uma vez)

# -----------------------------------------------------------------------
# Estilos (thumbnail com selo redondo da imobiliária)
# -----------------------------------------------------------------------
st.markdown("""
<style>
.card-imovel {
    border: 1px solid #e6e6e6;
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 18px;
    background: white;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}
.thumb-wrap {
    position: relative;
    width: 100%;
    height: 180px;
    background-color: #f2f2f2;
}
.thumb-wrap img.thumb {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
}
.logo-badge {
    position: absolute;
    bottom: 8px;
    left: 8px;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    border: 2px solid white;
    background: white;
    object-fit: cover;
    box-shadow: 0 1px 4px rgba(0,0,0,0.3);
}
.card-body {
    padding: 10px 14px 14px 14px;
}
.card-preco {
    font-size: 1.1rem;
    font-weight: 700;
    color: #1a7a3c;
    margin: 4px 0;
}
.card-bairro {
    color: #555;
    font-size: 0.9rem;
}
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------
# Sidebar: status + botão de atualização manual + filtros
# -----------------------------------------------------------------------
st.sidebar.header("🏠 Imóveis para Alugar")

ultima = db.ultima_execucao()
if ultima:
    st.sidebar.caption(f"Última varredura: {ultima['executado_em']} "
                        f"({ultima['imoveis_coletados']} imóveis)")
    if ultima.get("erro"):
        st.sidebar.warning(f"Aviso na última varredura: {ultima['erro']}")
else:
    st.sidebar.caption("Nenhuma varredura executada ainda.")

if st.sidebar.button("🔄 Atualizar agora", use_container_width=True):
    with st.spinner("Buscando imóveis nos sites configurados..."):
        rodar_agora_async().join()
    st.sidebar.success("Atualizado!")
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("Filtros")

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

bairros_disponiveis = db.listar_bairros()
bairros_selecionados = st.sidebar.multiselect(
    "Bairro", options=bairros_disponiveis, default=[]
)

# -----------------------------------------------------------------------
# Busca no banco com os filtros aplicados
# -----------------------------------------------------------------------
imoveis = db.listar_imoveis(
    preco_min=faixa[0],
    preco_max=faixa[1],
    bairros=bairros_selecionados or None,
)

st.title("Imóveis disponíveis para alugar")
st.caption(f"{len(imoveis)} imóveis encontrados")

if not imoveis:
    st.info(
        "Nenhum imóvel no banco ainda (ou nenhum bateu com os filtros). "
        "Clique em '🔄 Atualizar agora' na barra lateral para rodar a primeira varredura."
    )
else:
    aba_lista, aba_mapa = st.tabs(["📋 Lista de imóveis", "🗺️ Mapa"])

    # ------------------- ABA LISTA (showpage / grid de cards) -------------------
    with aba_lista:
        colunas_por_linha = 3
        colunas = st.columns(colunas_por_linha)
        for i, imovel in enumerate(imoveis):
            col = colunas[i % colunas_por_linha]
            with col:
                thumb = imovel["thumbnail_url"] or "https://via.placeholder.com/400x260?text=Sem+foto"
                logo = imovel["logo_url"] or ""
                preco = f"R$ {imovel['preco']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if imovel["preco"] else "Consultar"
                bairro = imovel["bairro"] or "Bairro não informado"
                cidade = imovel["cidade"] or ""
                titulo = imovel["titulo"] or imovel["imobiliaria"]

                st.markdown(f"""
                <div class="card-imovel">
                    <div class="thumb-wrap">
                        <img class="thumb" src="{thumb}" />
                        <img class="logo-badge" src="{logo}" />
                    </div>
                    <div class="card-body">
                        <div><strong>{titulo}</strong></div>
                        <div class="card-preco">{preco}/mês</div>
                        <div class="card-bairro">{bairro}{', ' + cidade if cidade else ''}</div>
                        <div style="font-size:0.8rem;color:#888;margin-top:4px;">{imovel['imobiliaria']}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
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
