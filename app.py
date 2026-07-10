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

cidades_disponiveis = db.listar_cidades()
cidades_selecionadas = st.sidebar.multiselect(
    "Cidade *", options=cidades_disponiveis, default=[],
    help="Escolha ao menos uma cidade para ver os imóveis.",
)

if not cidades_selecionadas:
    st.sidebar.info("⬆️ Selecione uma cidade para liberar os demais filtros.")

    st.title("Imóveis disponíveis para alugar")
    st.info("👋 Para começar, escolha uma **cidade** na barra lateral.")
    st.stop()

bairros_disponiveis = db.listar_bairros(cidades=cidades_selecionadas)
bairros_selecionados = st.sidebar.multiselect(
    "Bairro", options=bairros_disponiveis, default=[]
)

tipos_disponiveis = db.listar_tipos(cidades=cidades_selecionadas, bairros=bairros_selecionados or None)
tipos_selecionados = st.sidebar.multiselect(
    "Tipo de imóvel", options=tipos_disponiveis, default=[]
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
                tipo_badge_html = f'<div class="tipo-badge">{imovel["tipo"]}</div>' if imovel.get("tipo") else ""

                st.markdown(f"""
                <div class="card-imovel">
                    <div class="thumb-wrap">
                        <img class="thumb" src="{thumb}" />
                        <img class="logo-badge" src="{logo}" />
                        {tipo_badge_html}
                    </div>
                    <div class="card-body">
                        <div class="card-titulo">{titulo}</div>
                        <div class="card-preco">{preco}/mês</div>
                        <div class="card-bairro">{bairro}{', ' + cidade if cidade else ''}</div>
                        <div class="card-imobiliaria">{imovel['imobiliaria']}</div>
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
