"""
Converte "bairro + cidade" em latitude/longitude usando Nominatim
(OpenStreetMap), com cache em banco para não repetir consultas e
respeitando o limite de 1 requisição/segundo exigido pela política
de uso do Nominatim.
"""
import time
import yaml
from pathlib import Path
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

import db

_CONFIG = yaml.safe_load((Path(__file__).parent / "sites_config.yaml").read_text(encoding="utf-8"))
_GEO_CFG = _CONFIG.get("geocodificacao", {})

_geolocator = Nominatim(user_agent=_GEO_CFG.get("user_agent", "imoveis-scraper-app"))
_geocode_rate_limited = RateLimiter(_geolocator.geocode, min_delay_seconds=1.1, max_retries=2)


def geocodificar_bairro(bairro: str, cidade: str):
    """Retorna (lat, lon) para um bairro+cidade, usando cache quando disponível."""
    if not bairro:
        return (None, None)

    cidade = cidade or ""
    chave = f"{bairro.strip().lower()}|{cidade.strip().lower()}"

    cache = db.get_geocode_cache(chave)
    if cache:
        return cache

    pais = _GEO_CFG.get("pais", "Brasil")
    consulta = f"{bairro}, {cidade}, {pais}" if cidade else f"{bairro}, {pais}"

    try:
        resultado = _geocode_rate_limited(consulta)
    except Exception:
        resultado = None

    if resultado:
        lat, lon = resultado.latitude, resultado.longitude
    else:
        # fallback: tenta geocodificar só a cidade, para pelo menos
        # posicionar o imóvel na região certa no mapa
        try:
            resultado_cidade = _geocode_rate_limited(f"{cidade}, {pais}") if cidade else None
        except Exception:
            resultado_cidade = None
        if resultado_cidade:
            lat, lon = resultado_cidade.latitude, resultado_cidade.longitude
        else:
            lat, lon = (None, None)

    db.set_geocode_cache(chave, lat, lon)
    return (lat, lon)
