"""Interface local do Agente de Expansão Imobiliária."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import streamlit as st
import yaml

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agente_expansao.config import (  # noqa: E402
    CONFIRMATION_PHRASE,
    PROPOSAL_DB_PATH,
)
from agente_expansao.collection import (  # noqa: E402
    candidate_site_key,
    collection_checkpoint_available,
    collection_preview,
    configured_sites,
    prepare_snapshot,
    proposal_preview,
    run_local_collection,
    save_selector_override,
    strategy_history,
)
from agente_expansao.engine import ExpansionEngine  # noqa: E402
from agente_expansao.integrations import ProjectAdapter  # noqa: E402
from agente_expansao.publication import (  # noqa: E402
    build_preview,
    diagnose,
    publish_pull_request,
    publish_snapshot_pull_request,
)
from agente_expansao.storage import Repository  # noqa: E402
from agente_expansao.visual_picker import pick_selectors  # noqa: E402
from agente_expansao.resources import recommended_workers  # noqa: E402
from agente_expansao.selector_config import (  # noqa: E402
    REQUIRED_SELECTORS,
    config_signature,
    list_persisted_overrides,
    proposal_override_is_stale,
    save_edited_override,
    validate_override,
)
from snapshot_publico import PUBLIC_DB_PATH  # noqa: E402


st.set_page_config(
    page_title="Agente de Expansão Imobiliária",
    page_icon="🏘️",
    layout="wide",
)


@st.cache_resource
def services():
    repository = Repository()
    adapter = ProjectAdapter()
    return repository, adapter, ExpansionEngine(repository, adapter)


@st.cache_data(ttl=86400, show_spinner=False)
def load_states():
    return ProjectAdapter().states()


@st.cache_data(ttl=86400, show_spinner=False)
def load_regions(state):
    return ProjectAdapter().regions(state)


@st.cache_data(ttl=86400, show_spinner=False)
def load_region_cities(region_id):
    return ProjectAdapter().cities_in_region(region_id)


@st.cache_data(ttl=86400, show_spinner=False)
def load_state_cities(state):
    return ProjectAdapter().cities_in_state(state)


repository, adapter, engine = services()

st.title("🏘️ Agente de Expansão Imobiliária")
st.caption(
    "Ambiente administrativo local. Nada é publicado automaticamente e a "
    "produção não é alterada por inspeções ou aprovações."
)

all_candidates = repository.list_candidates()
counts = {}
for candidate in all_candidates:
    counts[candidate["status"]] = counts.get(candidate["status"], 0) + 1
c1, c2, c3, c4 = st.columns(4)
c1.metric("Candidatos", len(all_candidates))
c2.metric("Em revisão", counts.get("revisao", 0))
c3.metric("Quarentena", counts.get("quarentena", 0))
c4.metric("Aprovados", counts.get("aprovado", 0))

tab_map, tab_review, tab_quarantine, tab_collect, tab_teach, tab_history, tab_publish = st.tabs(
    [
        "1. Mapear", "2. Revisar", "3. Quarentena", "4. Raspar e visualizar",
        "5. Ensinar manualmente", "Histórico", "Publicar",
    ]
)

with tab_map:
    st.subheader("Escolha a área de expansão")
    st.write(
        "O mapa territorial vem do IBGE. A busca procura sites oficiais e tenta "
        "encontrar a página específica de imóveis para alugar."
    )
    try:
        states = load_states()
        labels = {f"{item['nome']} ({item['sigla']})": item for item in states}
        default = next(
            (i for i, label in enumerate(labels) if label.endswith("(MG)")), 0
        )
        state_label = st.selectbox("Estado", list(labels), index=default)
        state = labels[state_label]
        scope = st.radio(
            "Escopo", ["Cidade", "Região imediata do IBGE", "Estado inteiro"],
            horizontal=True,
        )
        chosen_cities: list[str] = []
        region_name = ""
        if scope == "Região imediata do IBGE":
            regions = load_regions(state["sigla"])
            region_map = {item["nome"]: item for item in regions}
            region_name = st.selectbox("Região", list(region_map))
            cities = load_region_cities(region_map[region_name]["id"])
            chosen_cities = st.multiselect(
                "Cidades a pesquisar", cities, default=cities[: min(5, len(cities))]
            )
        elif scope == "Cidade":
            cities = load_state_cities(state["sigla"])
            chosen_cities = [
                st.selectbox(
                    "Cidade",
                    cities,
                    index=cities.index("Ipatinga") if "Ipatinga" in cities else 0,
                )
            ]
        limit = st.slider("Máximo de candidatos", 3, 15, 6)
        if st.button("🔎 Descobrir imobiliárias", type="primary"):
            with st.spinner("Consultando fontes públicas e validando páginas..."):
                found = adapter.discover(
                    state=state["sigla"],
                    state_name=state["nome"],
                    cities=[] if scope == "Estado inteiro" else chosen_cities,
                    region=region_name,
                    limit=limit,
                )
                ids = engine.register_discovery(found)
            skipped = len(adapter.last_skipped)
            st.success(
                f"{len(ids)} candidato(s) novo(s) registrado(s). "
                f"{skipped} imobiliária(s) já cadastrada(s) foram desconsideradas."
            )
            st.rerun()
    except Exception as exc:
        st.error(f"Não foi possível consultar o mapa territorial: {exc}")

    st.divider()
    st.subheader("Adicionar um site conhecido")
    with st.form("manual_candidate"):
        col1, col2 = st.columns(2)
        manual_name = col1.text_input("Nome da imobiliária")
        manual_city = col2.text_input("Cidade")
        manual_url = st.text_input("Site oficial ou página de aluguel")
        if st.form_submit_button("Adicionar à fila"):
            from urllib.parse import urlparse

            url = manual_url.strip()
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            domain = (urlparse(url).hostname or "").removeprefix("www.")
            if not domain:
                st.error("Informe uma URL válida.")
            else:
                engine.register_discovery([{
                    "domain": domain,
                    "name": manual_name,
                    "state": "",
                    "region": "",
                    "city": manual_city,
                    "official_url": url,
                    "rental_url": url,
                    "discovery_score": 0,
                }])
                st.success("Site adicionado.")
                st.rerun()


def render_candidate(candidate: dict, prefix: str) -> None:
    st.markdown(f"#### {candidate.get('name') or candidate['domain']}")
    st.write(
        f"**Cidade:** {candidate.get('city') or 'não confirmada'} · "
        f"**Status:** `{candidate['status']}` · "
        f"**Confiança:** {candidate['confidence']:.0%}"
    )
    st.link_button("Abrir página", candidate.get("rental_url") or candidate["official_url"])
    rates = candidate.get("validation", {}).get("taxas_campos", {})
    if rates:
        cols = st.columns(4)
        for col, field in zip(cols, ("titulo", "preco", "thumbnail", "link")):
            col.metric(field.capitalize(), f"{float(rates.get(field, 0)):.0%}")
    if candidate.get("last_error"):
        st.error(candidate["last_error"])
    if candidate.get("validation", {}).get("motivos_validacao"):
        st.warning(" ".join(candidate["validation"]["motivos_validacao"]))

    col_inspect, col_reject = st.columns(2)
    if col_inspect.button("Inspecionar com JavaScript", key=f"{prefix}_inspect_{candidate['id']}"):
        with st.spinner("Abrindo Chromium, renderizando JavaScript e validando cards..."):
            result = engine.inspect(candidate["id"])
        if result.get("error"):
            st.error(result["error"])
        else:
            st.success(f"Inspeção concluída: {result['status']}.")
        st.rerun()
    if col_reject.button("Descartar", key=f"{prefix}_reject_{candidate['id']}"):
        repository.set_status(candidate["id"], "descartado", "Descartado pelo administrador.")
        st.rerun()

    selectors = candidate.get("selectors") or {}
    if selectors:
        with st.expander("Revisar seletores detectados"):
            edited = st.text_area(
                "Seletores (JSON)",
                json.dumps(selectors, ensure_ascii=False, indent=2),
                height=230,
                key=f"{prefix}_selectors_{candidate['id']}",
            )
            note = st.text_input(
                "Observação da correção", key=f"{prefix}_note_{candidate['id']}"
            )
            learn = st.checkbox(
                "Usar esta correção como aprendizado para a mesma plataforma",
                value=True,
                key=f"{prefix}_learn_{candidate['id']}",
            )
            if st.button(
                "Aprovar manualmente", type="primary",
                key=f"{prefix}_approve_{candidate['id']}"
            ):
                try:
                    engine.approve(candidate["id"], json.loads(edited), note, learn)
                except (ValueError, json.JSONDecodeError) as exc:
                    st.error(str(exc))
                else:
                    st.success("Aprovado. Ainda não foi publicado.")
                    st.rerun()


def render_property_preview(rows: list[dict], maximum: int = 12) -> None:
    if not rows:
        st.info("Nenhum imóvel disponível para pré-visualização.")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption(f"Amostra visual dos primeiros {min(maximum, len(rows))} imóveis")
    columns = st.columns(3)
    for index, item in enumerate(rows[:maximum]):
        with columns[index % 3]:
            with st.container(border=True):
                thumbnail = str(item.get("thumbnail_url") or "").strip()
                parsed_thumbnail = urlsplit(thumbnail)
                if parsed_thumbnail.scheme in {"http", "https"} and parsed_thumbnail.netloc:
                    st.image(thumbnail, use_container_width=True)
                elif thumbnail:
                    st.caption("Imagem indisponível para pré-visualização.")
                st.write(item.get("titulo") or item.get("imobiliaria") or "Sem título")
                price = item.get("preco")
                st.write(
                    f"R$ {price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    if price is not None else "Preço sob consulta"
                )
                st.caption(
                    " · ".join(filter(None, (item.get("bairro"), item.get("cidade"))))
                )
                if item.get("url"):
                    st.link_button("Abrir anúncio", item["url"], use_container_width=True)


with tab_review:
    review = repository.list_candidates(["pendente", "revisao", "erro"])
    if not review:
        st.info("Nenhum candidato aguardando revisão.")
    for item in review:
        with st.container(border=True):
            render_candidate(item, "review")

with tab_quarantine:
    st.subheader("Baixa confiança")
    st.write(
        "Itens daqui nunca avançam sozinhos. Corrija e aprove manualmente ou descarte."
    )
    quarantined = repository.list_candidates(["quarentena"])
    if not quarantined:
        st.info("A quarentena está vazia.")
    for item in quarantined:
        with st.container(border=True):
            render_candidate(item, "quarantine")

with tab_collect:
    st.subheader("Raspagem robusta no seu computador")
    st.write(
        "A coleta mede CPU e memória antes de cada lote e usa o máximo seguro naquele "
        "momento, com três tentativas por imobiliária. O resultado fica em um banco "
        "local separado e não altera o site público."
    )
    current_capacity = recommended_workers("browser")
    r1, r2, r3 = st.columns(3)
    r1.metric("Navegadores agora", current_capacity["workers"])
    r2.metric("CPU em uso", f"{current_capacity['cpu_percent']:.0f}%")
    r3.metric("RAM disponível", f"{current_capacity['available_ram_gb']:.1f} GB")
    st.caption(
        "O número é recalculado durante a execução e diminui automaticamente se o "
        "Windows ficar sob pressão. Fontes por API podem usar concorrência maior."
    )
    sites = configured_sites()
    site_labels = {key: site.get("nome") or key for key, site in sites.items()}
    collection_scope = st.radio(
        "O que deseja raspar agora?",
        ["Todas as imobiliárias", "Somente as selecionadas"],
        horizontal=True,
    )
    collection_sites = list(site_labels)
    if collection_scope == "Somente as selecionadas":
        collection_sites = st.multiselect(
            "Imobiliárias", list(site_labels), format_func=lambda key: site_labels[key]
        )
    checkpoint_available = collection_checkpoint_available()
    if checkpoint_available:
        st.info(
            "Há uma raspagem interrompida salva. Você pode continuar sem repetir "
            "as imobiliárias já concluídas."
        )
        checkpoint_choice = st.radio(
            "Progresso interrompido",
            ["Retomar de onde parou", "Descartar e começar novamente"],
            horizontal=True,
        )
        fresh_collection = checkpoint_choice == "Descartar e começar novamente"
    else:
        fresh_collection = st.checkbox(
            "Começar um banco local novo",
            value=collection_scope == "Todas as imobiliárias",
            help="O banco anterior é preservado como backup antes da troca.",
        )
    if st.button(
        "Executar raspagem local", type="primary", disabled=not collection_sites
    ):
        with st.spinner("Raspando e validando. Isso pode levar vários minutos..."):
            try:
                result = run_local_collection(
                    None if collection_scope == "Todas as imobiliárias" else collection_sites,
                    fresh=fresh_collection,
                    workers=0,
                    attempts=3,
                )
            except Exception as exc:
                repository.log("coleta_local", str(exc), level="error")
                st.error(f"A raspagem local falhou: {exc}")
            else:
                repository.log(
                    "coleta_local",
                    f"Coleta concluída com {result['total']} imóveis no banco local.",
                    details={
                        "agencies": result.get("agencies", {}),
                        "error": result.get("error"),
                    },
                )
                resumed = len(result.get("sites_retomados", []))
                suffix = f" {resumed} imobiliária(s) concluída(s) foram reaproveitadas." if resumed else ""
                st.success(
                    f"Coleta concluída: {result['total']} imóveis disponíveis.{suffix}"
                )

    local_preview = collection_preview()
    if local_preview.get("available"):
        st.divider()
        p1, p2, p3 = st.columns(3)
        p1.metric("Imóveis locais", local_preview.get("total", 0))
        p2.metric("Imobiliárias", len(local_preview.get("agencies", {})))
        p3.metric(
            "Com preço", f"{local_preview.get('quality', {}).get('preco', 0):.0%}"
        )
        failed = [
            row for row in local_preview.get("statuses", [])
            if row.get("status") in {"erro", "interrompido"}
        ]
        if failed:
            st.warning(f"{len(failed)} imobiliária(s) apresentaram erro.")
            st.dataframe(failed, use_container_width=True, hide_index=True)
        render_property_preview(local_preview.get("rows", []))

        st.divider()
        st.subheader("Preparar o que será enviado")
        snapshot_mode_label = st.radio(
            "Modo do snapshot",
            ["Substituição completa", "Atualização parcial"],
            horizontal=True,
        )
        partial_sites: list[str] = []
        if snapshot_mode_label == "Atualização parcial":
            if not PUBLIC_DB_PATH.is_file():
                st.info(
                    "Ao preparar, o agente consultará o snapshot atual no GitHub. "
                    "Se ainda não existir, será necessário publicar primeiro uma substituição completa."
                )
            partial_sites = st.multiselect(
                "Substituir somente estas imobiliárias",
                sorted(local_preview.get("agencies", {})),
                format_func=lambda key: site_labels.get(key, key),
            )
        can_prepare = snapshot_mode_label == "Substituição completa" or bool(partial_sites)
        if st.button("Gerar prévia para publicação", disabled=not can_prepare):
            try:
                validation = prepare_snapshot(
                    "complete" if snapshot_mode_label == "Substituição completa" else "partial",
                    set(partial_sites),
                )
            except Exception as exc:
                st.error(str(exc))
            else:
                repository.log(
                    "snapshot",
                    f"Prévia criada com {validation['total']} imóveis.",
                    details=validation,
                )
                st.success("Snapshot preparado. Revise a prévia abaixo antes de publicar.")

    prepared = proposal_preview() if PROPOSAL_DB_PATH.is_file() else {}
    if prepared:
        st.divider()
        st.subheader("Prévia exata do snapshot preparado")
        if prepared.get("valid"):
            st.success(
                f"Snapshot válido: {prepared['total']} imóveis de "
                f"{len(prepared.get('agencies', {}))} imobiliárias."
            )
        else:
            st.error(" ".join(prepared.get("errors", [])))
        render_property_preview(prepared.get("rows", []))

with tab_teach:
    st.subheader("Ensinar caminhos clicando no site")
    st.write(
        "O navegador abrirá normalmente. Navegue até a página de aluguel, clique em "
        "‘Começar seleção’, escolha card, link, título, preço e imagem e depois ensine "
        "como carregar os demais imóveis."
    )
    sites = configured_sites()
    targets = {
        f"site:{key}": f"Cadastrada — {site.get('nome') or key}"
        for key, site in sites.items()
    }
    teach_candidates = repository.list_candidates(
        ["pendente", "revisao", "quarentena", "erro", "aprovado"]
    )
    targets.update({
        f"candidate:{item['id']}": f"Candidata — {item.get('name') or item['domain']}"
        for item in teach_candidates
    })
    target = st.selectbox("Imobiliária a ensinar", list(targets), format_func=targets.get)
    target_type, target_id = target.split(":", 1)
    if target_type == "site":
        target_site_key = target_id
        target_base_url = sites[target_id].get("base_url")
        default_url = sites[target_id].get("listagem_url") or sites[target_id].get("base_url")
    else:
        selected_candidate = next(
            item for item in teach_candidates if item["id"] == int(target_id)
        )
        target_site_key = candidate_site_key(selected_candidate)
        target_base_url = selected_candidate["official_url"]
        default_url = selected_candidate.get("rental_url") or selected_candidate["official_url"]
    persisted_for_target = list_persisted_overrides().get(target_site_key) or {}
    default_url = persisted_for_target.get("listagem_url") or default_url
    picker_url = st.text_input("Página inicial", value=default_url, key=f"picker_url_{target}")
    auto_col, visual_col = st.columns(2)
    if auto_col.button("Detectar caminhos automaticamente", type="primary"):
        with st.spinner("Analisando os cards e validando os campos encontrados..."):
            try:
                inspection = adapter.inspect(picker_url)
                if inspection.get("error"):
                    raise ValueError(inspection["error"])
                selectors = inspection.get("selectors") or {}
                if not {"card", "link", "preco"}.issubset(selectors):
                    raise ValueError(
                        "A página não forneceu uma amostra suficiente. Use a seleção visual."
                    )
                for field in REQUIRED_SELECTORS:
                    st.session_state.pop(f"manual_path_{target}_{field}", None)
                st.session_state.pop(f"manual_pagination_{target}", None)
                st.session_state.pop(f"manual_filters_{target}", None)
                pagination = persisted_for_target.get("paginacao") or {}
                filters = persisted_for_target.get("filtros") or {}
                signature = config_signature({
                    "url": inspection.get("url") or picker_url,
                    "seletores": selectors,
                    "paginacao": pagination,
                    "filtros": filters,
                })
                st.session_state["manual_picker_result"] = {
                    "target": target,
                    "url": inspection.get("url") or picker_url,
                    "selectors": selectors,
                    "pagination": pagination,
                    "filters": filters,
                    "validation": inspection,
                    "validation_signature": signature,
                    "automatic": True,
                }
                st.rerun()
            except Exception as exc:
                st.error(f"A detecção automática não foi concluída: {exc}")
    if visual_col.button("Abrir navegador para selecionar"):
        with st.spinner("Aguardando sua seleção no navegador externo..."):
            try:
                picked = pick_selectors(picker_url)
                checked = adapter.validate_learned_selectors(
                    picked["url"], picked["selectors"]
                )
                for field in REQUIRED_SELECTORS:
                    st.session_state.pop(f"manual_path_{target}_{field}", None)
                st.session_state.pop(f"manual_pagination_{target}", None)
                st.session_state.pop(f"manual_filters_{target}", None)
                st.session_state["manual_picker_result"] = {
                    "target": target,
                    **picked,
                    "validation": checked,
                    "validation_signature": config_signature({
                        "url": picked["url"],
                        "seletores": picked["selectors"],
                        "paginacao": picked.get("pagination") or {},
                        "filtros": picked.get("filters") or {},
                    }),
                }
            except Exception as exc:
                st.error(str(exc))

    manual = st.session_state.get("manual_picker_result")
    if (
        (not manual or manual.get("target") != target)
        and set(REQUIRED_SELECTORS).issubset(persisted_for_target.get("seletores") or {})
    ):
        manual = {
            "target": target,
            "url": persisted_for_target.get("listagem_url") or picker_url,
            "selectors": persisted_for_target["seletores"],
            "pagination": persisted_for_target.get("paginacao") or {},
            "filters": persisted_for_target.get("filtros") or {},
            "validation": {},
            "validation_signature": "",
            "loaded_from_saved": True,
        }
    if manual and manual.get("target") == target:
        st.markdown("### Ajustar caminhos aprendidos")
        if manual.get("loaded_from_saved"):
            st.info("O aprendizado salvo desta imobiliária foi carregado para edição.")
        elif manual.get("automatic"):
            ai_info = (manual.get("validation") or {}).get("ia") or {}
            if ai_info.get("used"):
                st.info("A heurística foi complementada pela IA e revalidada no site.")
            else:
                st.info("Os caminhos foram detectados e validados automaticamente no site.")
        st.caption(
            "Os valores abaixo vieram da seleção visual. Você pode substituir "
            "qualquer caminho por um seletor CSS copiado do Inspetor do navegador."
        )
        edited_selectors = dict(manual.get("selectors") or {})
        editor_version = manual.get("validation_signature") or config_signature({
            "url": manual.get("url"),
            "seletores": manual.get("selectors") or {},
            "paginacao": manual.get("pagination") or {},
            "filtros": manual.get("filters") or {},
        })
        selector_labels = {
            "card": "Card", "link": "Link", "titulo": "Título",
            "preco": "Preço", "thumbnail": "Thumbnail",
        }
        selector_columns = st.columns(2)
        for index, field in enumerate(REQUIRED_SELECTORS):
            with selector_columns[index % 2]:
                edited_selectors[field] = st.text_input(
                    selector_labels[field],
                    value=edited_selectors.get(field, ""),
                    key=f"manual_path_{target}_{editor_version}_{field}",
                )
        st.write("**Navegação aprendida**")
        pagination_text = st.text_area(
            "Paginação (YAML editável)",
            value=yaml.safe_dump(
                manual.get("pagination") or {}, allow_unicode=True, sort_keys=False
            ),
            key=f"manual_pagination_{target}_{editor_version}",
        )
        filters_text = st.text_area(
            "Filtros (YAML editável)",
            value=yaml.safe_dump(
                manual.get("filters") or {}, allow_unicode=True, sort_keys=False
            ),
            key=f"manual_filters_{target}_{editor_version}",
        )

        try:
            edited_pagination = yaml.safe_load(pagination_text) or {}
            edited_filters = yaml.safe_load(filters_text) or {}
            if not isinstance(edited_pagination, dict) or not isinstance(edited_filters, dict):
                raise ValueError("Paginação e filtros devem conter campos no formato chave: valor.")
            manual_draft = {
                "base_url": persisted_for_target.get("base_url") or target_base_url,
                "listagem_url": manual["url"],
                "seletores": edited_selectors,
                "paginacao": edited_pagination,
                "filtros": edited_filters,
            }
            validate_override(manual_draft)
            manual_error = ""
            manual_signature = config_signature({
                "url": manual["url"],
                "seletores": edited_selectors,
                "paginacao": edited_pagination,
                "filtros": edited_filters,
            })
        except Exception as exc:
            manual_draft = None
            manual_error = str(exc)
            manual_signature = ""
            st.warning(f"Revise os caminhos: {exc}")

        test_is_current = (
            bool(manual_signature)
            and manual.get("validation_signature") == manual_signature
        )
        if not test_is_current and manual_signature:
            if manual.get("loaded_from_saved") and not manual.get("validation_signature"):
                st.info("Teste a configuração carregada antes de salvar.")
            else:
                st.info("Você alterou os caminhos. Teste novamente antes de salvar.")
        if st.button("Testar caminhos editados", key=f"test_manual_paths_{target}"):
            try:
                if manual_draft is None:
                    raise ValueError(manual_error)
                checked = adapter.validate_learned_selectors(
                    manual["url"], manual_draft["seletores"]
                )
                st.session_state["manual_picker_result"] = {
                    **manual,
                    "selectors": edited_selectors,
                    "pagination": edited_pagination,
                    "filters": edited_filters,
                    "validation": checked,
                    "validation_signature": manual_signature,
                }
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível testar: {exc}")

        validation = manual.get("validation", {}) if test_is_current else {}
        if test_is_current:
            rates = validation.get("taxas_campos", {})
            cols = st.columns(4)
            for col, field in zip(cols, ("titulo", "preco", "thumbnail", "link")):
                col.metric(field.capitalize(), f"{float(rates.get(field, 0)):.0%}")
            if validation.get("publicavel"):
                st.success("Os caminhos passaram na validação automática.")
            else:
                st.warning(" ".join(validation.get("motivos_validacao", [])))
        manual_override = st.checkbox(
            "Revisei visualmente e quero salvar mesmo com o aviso acima.",
            disabled=not test_is_current or bool(validation.get("publicavel")),
        )
        if st.button(
            "Salvar aprendizado",
            disabled=(
                not test_is_current
                or (not validation.get("publicavel") and not manual_override)
            ),
        ):
            try:
                if manual_draft is None:
                    raise ValueError(manual_error)
                edited_snapshot = {
                    **persisted_for_target,
                    "listagem_url": manual["url"],
                    "seletores": edited_selectors,
                    "paginacao": edited_pagination,
                    "filtros": edited_filters,
                }
                if persisted_for_target:
                    save_edited_override(
                        target_site_key,
                        edited_snapshot,
                        tested_signature=config_signature(edited_snapshot),
                        test_result=validation,
                        force=not bool(validation.get("publicavel")),
                        justification=(
                            "Revisado visualmente no fluxo Ensinar caminhos."
                            if not validation.get("publicavel") else ""
                        ),
                    )
                if target_type == "site":
                    if not persisted_for_target:
                        save_selector_override(
                            target_id, manual["url"], edited_selectors,
                            pagination=edited_pagination,
                            filters=edited_filters,
                        )
                    repository.log(
                        "aprendizado_visual",
                        f"Seletores visuais salvos para {target_id}.",
                        details={
                            **manual,
                            "selectors": edited_selectors,
                            "pagination": edited_pagination,
                            "filters": edited_filters,
                            "validation": validation,
                        },
                    )
                else:
                    candidate_id = int(target_id)
                    candidate = repository.get_candidate(candidate_id)
                    learned_site_key = candidate_site_key(candidate)
                    if not persisted_for_target:
                        save_selector_override(
                            learned_site_key,
                            manual["url"],
                            edited_selectors,
                            {
                                "nome": candidate.get("name") or candidate["domain"],
                                "base_url": candidate["official_url"],
                                "cidade_padrao": candidate.get("city") or "",
                                "paginacao": {"tipo": "nenhuma"},
                            },
                            pagination=edited_pagination,
                            filters=edited_filters,
                        )
                    result = {
                        **validation,
                        "url": manual["url"],
                        "selectors": edited_selectors,
                        "confidence": validation.get("qualidade_extracao", 0),
                        "platform": candidate.get("platform") or "manual",
                        "manual": True,
                    }
                    repository.save_inspection(candidate_id, result, "revisao")
                    engine.approve(
                        candidate_id,
                        edited_selectors,
                        "Seleção visual manual.",
                        True,
                    )
                del st.session_state["manual_picker_result"]
                st.success("Aprendizado salvo e disponível nas próximas varreduras locais.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

with tab_history:
    st.subheader("Histórico e erros")
    learned_history = strategy_history()
    if learned_history:
        st.markdown("### Estratégias de navegação")
        st.dataframe(
            [
                {
                    "Quando": item.get("quando", ""),
                    "Imobiliária": item.get("site_key", ""),
                    "Ação": item.get("acao", ""),
                    "Tipo": (item.get("estrategia") or {}).get("tipo", ""),
                    "Imóveis": item.get("imoveis", ""),
                    "Erro": item.get("erro", ""),
                }
                for item in learned_history
            ],
            use_container_width=True,
            hide_index=True,
        )
    st.markdown("### Atividades gerais")
    events = repository.list_events()
    if events:
        st.dataframe(
            [
                {
                    "Quando": item["created_at"],
                    "Nível": item["level"],
                    "Ação": item["action"],
                    "Site": item.get("domain") or "",
                    "Mensagem": item["message"],
                }
                for item in events
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Nenhum evento registrado.")

with tab_publish:
    st.subheader("Publicação manual e segura")
    st.write(
        "A publicação cria uma **branch separada e um pull request** no GitHub. "
        "Ela não envia commits diretamente para `main` e não faz merge."
    )
    diagnosis = diagnose()
    if diagnosis["available"]:
        st.success("GitHub autenticado e repositório de destino confirmado.")
    else:
        st.warning(diagnosis["reason"])

    st.markdown("### 1. Publicar o banco de imóveis")
    snapshot = proposal_preview() if PROPOSAL_DB_PATH.is_file() else {}
    stale_override = proposal_override_is_stale()
    if stale_override:
        st.warning("A configuração aprendida mudou depois da prévia. Gere e revise uma nova prévia antes de publicar.")
    if not snapshot:
        st.info(
            "Primeiro gere e revise uma prévia em ‘Raspar e visualizar’."
        )
    elif snapshot.get("valid"):
        st.success(
            f"Pronto para proposta: {snapshot['total']} imóveis de "
            f"{len(snapshot.get('agencies', {}))} imobiliárias."
        )
        st.json({
            "qualidade": snapshot.get("quality", {}),
            "imóveis_por_imobiliária": snapshot.get("agencies", {}),
            "checksum": snapshot.get("sha256"),
        })
    else:
        st.error("Snapshot bloqueado: " + " ".join(snapshot.get("errors", [])))
    snapshot_confirmation = st.text_input(
        f"Para publicar o banco, digite: {CONFIRMATION_PHRASE}",
        key="snapshot_confirmation",
    )
    snapshot_confirmed = st.checkbox(
        "Revisei a prévia e quero criar o pull request do banco público.",
        key="snapshot_confirmed",
    )
    if st.button(
        "Criar pull request do banco",
        type="primary",
        disabled=not (
            snapshot.get("valid")
            and snapshot_confirmed
            and snapshot_confirmation == CONFIRMATION_PHRASE
            and diagnosis["available"]
            and not stale_override
        ),
    ):
        try:
            result = publish_snapshot_pull_request(snapshot_confirmation)
        except Exception as exc:
            repository.record_publication([], "erro", str(exc))
            st.error(f"Publicação não realizada: {exc}")
        else:
            repository.record_publication(
                [], "proposto", "Pull request do snapshot criado.",
                result["branch"], result["pull_request_url"],
            )
            st.success(
                "Pull request criado. O banco público só mudará depois da revisão e do merge."
            )
            st.link_button("Abrir pull request", result["pull_request_url"])

    st.divider()
    st.markdown("### 2. Publicar novas imobiliárias aprovadas")
    approved = repository.list_candidates(["aprovado"])
    selected_ids = st.multiselect(
        "Candidatos aprovados",
        [item["id"] for item in approved],
        format_func=lambda candidate_id: next(
            item.get("name") or item["domain"]
            for item in approved if item["id"] == candidate_id
        ),
    )
    selected = [item for item in approved if item["id"] in selected_ids]
    if selected:
        st.code(build_preview(selected), language="yaml")
    confirmation = st.text_input(
        f"Para publicar as configurações, digite: {CONFIRMATION_PHRASE}",
        key="config_confirmation",
    )
    confirmed = st.checkbox(
        "Confirmo que revisei os seletores e quero criar a proposta no GitHub.",
        key="config_confirmed",
    )
    if st.button(
        "Criar pull request das configurações",
        type="primary",
        disabled=not (
            selected and confirmed and confirmation == CONFIRMATION_PHRASE
            and diagnosis["available"]
        ),
    ):
        try:
            result = publish_pull_request(selected, confirmation)
        except Exception as exc:
            repository.record_publication(
                selected_ids, "erro", str(exc)
            )
            st.error(f"Publicação não realizada: {exc}")
        else:
            repository.record_publication(
                selected_ids, "proposto", "Pull request criado.",
                result["branch"], result["pull_request_url"]
            )
            for candidate_id in selected_ids:
                repository.set_status(
                    candidate_id, "proposto",
                    f"Proposta criada em {result['pull_request_url']}"
                )
            st.success("Pull request criado. Produção continua inalterada até o merge.")
            st.link_button("Abrir pull request", result["pull_request_url"])
