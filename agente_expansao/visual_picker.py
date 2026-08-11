"""Seletor visual Playwright para ensinar campos e navegação sem DevTools."""
from __future__ import annotations

import json
import re
import time
from urllib.parse import parse_qsl, quote, urljoin, urlparse, urlsplit, urlunsplit

from playwright.sync_api import sync_playwright


FIELDS = ("card", "link", "titulo", "preco", "thumbnail")
FIELD_LABELS = {
    "card": "o CARD inteiro do imóvel",
    "link": "o LINK que abre o imóvel",
    "titulo": "o TÍTULO",
    "preco": "o PREÇO",
    "thumbnail": "a IMAGEM",
}

PICKER_SCRIPT = r"""
(() => {
  if (window.__agentePickerInstalled) return;
  window.__agentePickerInstalled = true;
  let active = false, index = 0, navigationMode = '', filterControl = null;
  const fields = ['card', 'link', 'titulo', 'preco', 'thumbnail'];
  const labels = {
    card: 'o CARD inteiro do imóvel', link: 'o LINK que abre o imóvel',
    titulo: 'o TÍTULO', preco: 'o PREÇO', thumbnail: 'a IMAGEM'
  };
  const bar = document.createElement('div');
  bar.id = '__agente_picker_bar';
  bar.style.cssText = 'position:fixed;z-index:2147483647;left:14px;right:14px;bottom:14px;padding:14px 18px;background:#11243a;color:white;border:2px solid #54d39a;border-radius:12px;font:16px Arial;box-shadow:0 6px 30px #0008';
  const button = (id, text) => `<button id="${id}" style="margin-left:8px;padding:8px 12px">${text}</button>`;
  bar.innerHTML = '<b>Agente de Expansão</b> — navegue até a listagem de aluguel. ' +
    button('__picker_start', 'Começar seleção') + button('__picker_cancel', 'Cancelar') +
    '<span id="__picker_status" style="margin-left:12px"></span><div id="__picker_actions" style="margin-top:10px"></div>';
  const mount = () => { if (document.body && !document.getElementById(bar.id)) document.body.appendChild(bar); };
  mount(); document.addEventListener('DOMContentLoaded', mount);
  const status = () => document.getElementById('__picker_status');
  const actions = () => document.getElementById('__picker_actions');
  const selector = (el) => {
    if (!el || el === document.body) return el ? el.tagName.toLowerCase() : '';
    const tag = el.tagName.toLowerCase();
    if (el.id && el.id.length < 70 && !/[0-9]{4,}/.test(el.id)) return '#' + CSS.escape(el.id);
    const name = el.getAttribute('name');
    if (name && name.length < 70) return `${tag}[name="${CSS.escape(name)}"]`;
    const classes = [...el.classList].filter(c => c.length < 60 && !/[0-9]{4,}/.test(c)).slice(0, 4);
    return tag + classes.map(c => '.' + CSS.escape(c)).join('');
  };
  const showNavigation = () => {
    active = false;
    status().textContent = 'Como este site mostra os demais imóveis?';
    actions().innerHTML = button('__nav_auto','Descobrir automaticamente') +
      button('__nav_button','Clicar em Carregar mais') + button('__nav_scroll','Rolagem infinita') +
      button('__nav_next','Link Próxima página') + button('__nav_filter','Dividir por filtros') +
      button('__nav_none','Página única');
  };
  const finishSimple = async mode => {
    actions().innerHTML = ''; status().textContent = 'Concluído. Aguarde o navegador fechar.';
    await window.agenteNavigation(mode, '', '{}', location.href);
  };
  document.addEventListener('click', async event => {
    const id = event.target.id || '';
    if (id === '__picker_start') {
      event.preventDefault(); active = true; index = 0; navigationMode = '';
      actions().innerHTML = ''; status().textContent = 'Agora clique em ' + labels[fields[index]] + '.'; return;
    }
    if (id === '__picker_cancel') {
      event.preventDefault(); await window.agenteCancel(); bar.remove(); return;
    }
    if (id === '__nav_auto') { event.preventDefault(); return finishSimple('auto'); }
    if (id === '__nav_scroll') { event.preventDefault(); return finishSimple('rolagem'); }
    if (id === '__nav_none') { event.preventDefault(); return finishSimple('nenhuma'); }
    if (id === '__nav_button' || id === '__nav_next' || id === '__nav_filter') {
      event.preventDefault(); navigationMode = id.replace('__nav_', ''); actions().innerHTML = '';
      status().textContent = navigationMode === 'button' ? 'Clique no botão Carregar mais.' :
        navigationMode === 'next' ? 'Clique no link Próxima página.' :
        'Clique no seletor de cidade, bairro, tipo ou preço.';
      return;
    }
    if (id === '__filter_auto') {
      event.preventDefault(); filterControl.apply_selector = '';
      return window.agenteNavigation('filtro', filterControl.selector, JSON.stringify(filterControl), location.href);
    }
    if (id === '__filter_apply') {
      event.preventDefault(); navigationMode = 'filter_apply'; actions().innerHTML = '';
      status().textContent = 'Agora clique no botão Aplicar/Buscar.'; return;
    }
    if (bar.contains(event.target)) return;

    if (navigationMode) {
      event.preventDefault(); event.stopPropagation(); event.stopImmediatePropagation();
      if (navigationMode === 'button') {
        const el = event.target.closest('a,button,[role="button"]') || event.target;
        await window.agenteNavigation('botao', selector(el), '{}', location.href);
      } else if (navigationMode === 'next') {
        const el = event.target.closest('a') || event.target;
        await window.agenteNavigation('proxima', selector(el), JSON.stringify({href:el.href || ''}), location.href);
      } else if (navigationMode === 'filter') {
        const el = event.target.closest('select') || event.target.closest('form,nav,section,div') || event.target;
        const options = el.tagName === 'SELECT' ? [...el.options]
          .filter(o => o.value && o.value !== '0' && o.value !== '-1').slice(0,60)
          .map(o => ({value:o.value,label:(o.textContent||'').trim()})) : [];
        const links = el.tagName === 'SELECT' ? [] : [...el.querySelectorAll('a[href]')]
          .map(a => a.href).filter((url,pos,all) => url && all.indexOf(url) === pos).slice(0,60);
        filterControl = {tipo: el.tagName === 'SELECT' ? 'select' : 'links', selector:selector(el), opcoes:options, urls:links};
        if (filterControl.tipo === 'select') {
          navigationMode = ''; status().textContent = 'O filtro precisa de um botão Aplicar/Buscar?';
          actions().innerHTML = button('__filter_auto','Não, aplica sozinho') + button('__filter_apply','Sim, escolher botão');
          return;
        }
        await window.agenteNavigation('filtro', filterControl.selector, JSON.stringify(filterControl), location.href);
      } else if (navigationMode === 'filter_apply') {
        const el = event.target.closest('a,button,[role="button"],input[type="submit"]') || event.target;
        filterControl.apply_selector = selector(el);
        await window.agenteNavigation('filtro', filterControl.selector, JSON.stringify(filterControl), location.href);
      }
      navigationMode = ''; actions().innerHTML = '';
      status().textContent = 'Concluído. Aguarde o navegador fechar.'; return;
    }

    if (!active) return;
    event.preventDefault(); event.stopPropagation(); event.stopImmediatePropagation();
    let element = event.target;
    if (fields[index] === 'link') element = event.target.closest('a') || event.target;
    if (fields[index] === 'thumbnail') element = event.target.closest('img') || event.target;
    element.style.outline = '4px solid #54d39a';
    await window.agenteRecord(fields[index], selector(element), location.href);
    index += 1;
    if (index >= fields.length) showNavigation();
    else status().textContent = 'Agora clique em ' + labels[fields[index]] + '.';
  }, true);
  document.addEventListener('mouseover', event => {
    if ((active || navigationMode) && !bar.contains(event.target)) event.target.style.outline = '3px solid #ffb74d';
  }, true);
  document.addEventListener('mouseout', event => {
    if ((active || navigationMode) && !bar.contains(event.target)) event.target.style.outline = '';
  }, true);
})();
"""


def _url_pagination_config(href: str, page_url: str, selector: str = "") -> dict:
    url = urljoin(page_url, href)
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    for key, value in pairs:
        if key.casefold() in {"page", "pagina", "página", "pg", "offset", "start"} and value.isdigit():
            query = "&".join(
                f"{quote(name, safe='[]')}=" +
                ("{pagina}" if name == key else quote(item, safe="/:,[]"))
                for name, item in pairs
            )
            numeric = int(value)
            increment = numeric if key.casefold() in {"offset", "start"} else 1
            return {
                "tipo": "url", "url_template": urlunsplit(
                    (parts.scheme, parts.netloc, parts.path, query, parts.fragment)
                ),
                "pagina_inicial": 0 if key.casefold() in {"offset", "start"} else 1,
                "proxima_pagina": numeric, "incremento": max(1, increment),
                "max_paginas": 100, "parar_sem_novos": 1,
                "aprendida_manualmente": True,
            }
    match = re.search(r"(?i)(/pages?|/paginas?|/p)/?(\d+)(?=/|$)", parts.path)
    if match:
        path = parts.path[:match.start(2)] + "{pagina}" + parts.path[match.end(2):]
        return {
            "tipo": "url", "url_template": urlunsplit(
                (parts.scheme, parts.netloc, path, parts.query, parts.fragment)
            ),
            "pagina_inicial": 1, "proxima_pagina": int(match.group(2)),
            "incremento": 1, "max_paginas": 100, "parar_sem_novos": 1,
            "aprendida_manualmente": True,
        }
    return {
        "tipo": "botao", "botao_selector": selector or "a[rel='next']",
        "max_cliques": 50, "espera_apos_clique_ms": 1500,
        "parar_sem_novos": 2, "aprendida_manualmente": True,
    }


def _navigation_config(navigation: dict, page_url: str) -> tuple[dict, dict | None]:
    mode = navigation.get("mode")
    selector = navigation.get("selector") or ""
    metadata = navigation.get("metadata") or {}
    if mode == "botao":
        return ({"tipo": "botao", "botao_selector": selector, "max_cliques": 50,
                 "espera_apos_clique_ms": 1500, "parar_sem_novos": 2,
                 "aprendida_manualmente": True}, None)
    if mode == "rolagem":
        return ({"tipo": "rolagem", "max_rolagens": 80,
                 "espera_apos_rolagem_ms": 1400, "parar_sem_novos": 3,
                 "aprendida_manualmente": True}, None)
    if mode == "proxima":
        return (_url_pagination_config(metadata.get("href", ""), page_url, selector), None)
    if mode == "filtro":
        filters = {
            "tipo": metadata.get("tipo", "select"),
            "seletor": selector,
            "opcoes": metadata.get("opcoes", []),
            "urls": metadata.get("urls", []),
            "aplicar_selector": metadata.get("apply_selector", ""),
            "espera_ms": 1500,
            "max_opcoes": 60,
            "ativo": True,
            "aprendida_manualmente": True,
        }
        return ({"tipo": "auto"}, filters)
    return ({"tipo": mode if mode in {"auto", "nenhuma"} else "auto"}, None)


def pick_selectors(url: str, timeout_seconds: int = 600) -> dict:
    if not urlparse(url).scheme:
        url = "https://" + url
    selected: dict[str, str] = {}
    state = {"cancelled": False, "done": False, "url": url, "navigation": {}}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()

        def record(_source, field, selector, page_url):
            if field in FIELDS:
                selected[field] = selector
                state["url"] = page_url

        def navigation(_source, mode, selector, metadata, page_url):
            state["navigation"] = {
                "mode": mode,
                "selector": selector,
                "metadata": json.loads(metadata or "{}"),
            }
            state["url"] = page_url
            state["done"] = True

        def cancel(_source):
            state["cancelled"] = True

        context.expose_binding("agenteRecord", record)
        context.expose_binding("agenteNavigation", navigation)
        context.expose_binding("agenteCancel", cancel)
        context.add_init_script(PICKER_SCRIPT)
        page = context.new_page()
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        page.evaluate(PICKER_SCRIPT)
        deadline = time.monotonic() + timeout_seconds
        try:
            while time.monotonic() < deadline:
                if state["cancelled"] or state["done"]:
                    break
                if page.is_closed():
                    break
                page.wait_for_timeout(250)
        finally:
            browser.close()
    if state["cancelled"]:
        raise RuntimeError("Seleção manual cancelada.")
    missing = [FIELD_LABELS[field] for field in FIELDS if field not in selected]
    if missing:
        raise RuntimeError("Seleção incompleta: faltou " + ", ".join(missing) + ".")
    if not state["done"]:
        raise RuntimeError("Seleção incompleta: faltou ensinar como carregar os demais imóveis.")
    pagination, filters = _navigation_config(state["navigation"], state["url"])
    return {
        "url": state["url"], "selectors": selected,
        "pagination": pagination, "filters": filters,
    }
