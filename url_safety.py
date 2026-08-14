"""Validação de destinos públicos antes de navegação automatizada."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests


DETECTOR_USER_AGENT = "MapaDoAluguelDetector/1.0"


def validar_url_publica(url: str, *, allowed_hosts: set[str] | None = None) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Use uma URL pública http ou https válida.")
    if parsed.username or parsed.password:
        raise ValueError("A URL não pode conter credenciais.")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("A porta da URL não é permitida.")
    host = parsed.hostname.casefold().rstrip(".")
    normalized_allowed = {
        item.casefold().rstrip(".").removeprefix("www.")
        for item in (allowed_hosts or set())
    }
    if normalized_allowed and host.removeprefix("www.") not in normalized_allowed:
        raise ValueError("O redirecionamento saiu do domínio autorizado.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ValueError("Não foi possível resolver o domínio da URL.") from exc
    if not addresses:
        raise ValueError("O domínio da URL não retornou endereço público.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("A URL aponta para uma rede local ou reservada.")
    return parsed.geturl()


def proteger_pagina(page, original_url: str) -> None:
    """Bloqueia requisições do navegador para redes privadas e redirects externos."""
    original_host = urlparse(original_url).hostname or ""

    def handle(route):
        try:
            allowed = {original_host} if route.request.resource_type == "document" else None
            validar_url_publica(route.request.url, allowed_hosts=allowed)
            route.continue_()
        except ValueError:
            route.abort()

    page.route("**/*", handle)


def verificar_robots(url: str, *, timeout: int = 12) -> str:
    """Falha fechado quando a política da fonte não pode ser confirmada."""
    validar_url_publica(url)
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    allowed_hosts = {parsed.hostname or ""}
    response = None
    for _ in range(6):
        validar_url_publica(robots_url, allowed_hosts=allowed_hosts)
        response = requests.get(
            robots_url, timeout=timeout, allow_redirects=False,
            headers={"User-Agent": DETECTOR_USER_AGENT},
        )
        if response.status_code not in {301, 302, 303, 307, 308}:
            break
        location = response.headers.get("Location")
        if not location:
            raise ValueError("O redirecionamento de robots.txt nÃ£o informou um destino.")
        robots_url = urljoin(robots_url, location)
    else:
        raise ValueError("A polÃ­tica robots.txt redirecionou vezes demais.")
    if response is None:
        raise ValueError("A polÃ­tica robots.txt nÃ£o pÃ´de ser consultada.")
    validar_url_publica(response.url, allowed_hosts=allowed_hosts)
    if response.status_code == 404:
        return "robots_ausente"
    if response.status_code != 200:
        raise ValueError(f"A política robots.txt não pôde ser confirmada (HTTP {response.status_code}).")
    parser = RobotFileParser()
    parser.set_url(response.url)
    parser.parse(response.text[:1_000_000].splitlines())
    if not parser.can_fetch(DETECTOR_USER_AGENT, url):
        raise ValueError("A política robots.txt não permite testar esta página.")
    return "robots_permite"
