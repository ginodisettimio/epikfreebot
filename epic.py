"""
Acceso a la Epic Games Store.

Este módulo es la única parte del bot que conoce la API de Epic y el formato
de sus fechas. Devuelve los juegos con claves en español para que el resto
del código no dependa del formato original.
"""

import os
from datetime import datetime

from dotenv import load_dotenv
from epicstore_api import EpicGamesStoreAPI


load_dotenv()
EPIC_IDIOMA = os.getenv("EPIC_LOCALE", "es-ES")
EPIC_PAIS = os.getenv("EPIC_COUNTRY", "AR")

URL_TIENDA = f"https://store.epicgames.com/{EPIC_IDIOMA}"

cliente_epic = EpicGamesStoreAPI(locale=EPIC_IDIOMA, country=EPIC_PAIS)


def _oferta_gratis(grupos_promocion: list | None) -> dict | None:
    """Devuelve la primera oferta con 100 % de descuento, o None."""
    for grupo in grupos_promocion or []:
        for oferta in grupo.get("promotionalOffers") or []:
            descuento = (oferta.get("discountSetting") or {}).get("discountPercentage")
            if descuento == 0:
                return oferta
    return None


def _url_juego(elemento: dict) -> str:
    """Arma el enlace a la página del juego en la tienda."""
    mapeos = (
        ((elemento.get("catalogNs") or {}).get("mappings") or [])
        + (elemento.get("offerMappings") or [])
    )
    slug = next((mapeo.get("pageSlug") for mapeo in mapeos if mapeo.get("pageSlug")), None)
    slug = slug or elemento.get("productSlug")
    return f"{URL_TIENDA}/p/{slug}" if slug else f"{URL_TIENDA}/free-games"


def _precio_juego(elemento: dict) -> str:
    """Devuelve el precio original del juego o 'Free-to-play' si es gratis."""
    formato = ((elemento.get("price") or {}).get("totalPrice") or {}).get("fmtPrice") or {}
    precio = formato.get("originalPrice") or "N/D"
    return "Free-to-play" if precio == "0" else precio


def fecha_corta(iso: str) -> str:
    """Convierte una fecha ISO ('2026-11-13T15:00:00.000Z') en '13/11/2026'."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d/%m/%Y")


def rango_fechas(juegos: list[dict]) -> str:
    """Devuelve el período de la promoción: '13/11/2026 - 20/11/2026'."""
    return f"{juegos[0]['inicio']} - {juegos[0]['fin']}"


def obtener_juegos(tipo: str) -> list[dict]:
    """
    Devuelve los juegos gratis de la Epic Games Store.

    tipo: "actuales" (gratis ahora) o "proximos" (gratis la semana que viene).
    """
    if tipo == "actuales":
        clave = "promotionalOffers"
    elif tipo == "proximos":
        clave = "upcomingPromotionalOffers"
    else:
        raise ValueError(f"Tipo de juego desconocido: {tipo}")

    datos = cliente_epic.get_free_games()
    elementos = datos["data"]["Catalog"]["searchStore"]["elements"]

    juegos = []
    for elemento in elementos:
        oferta = _oferta_gratis((elemento.get("promotions") or {}).get(clave))
        if oferta is None:
            continue
        juegos.append({
            "titulo": elemento.get("title", "Sin nombre"),
            "url": _url_juego(elemento),
            "precio_normal": _precio_juego(elemento),
            "inicio": fecha_corta(oferta["startDate"]),
            "fin": fecha_corta(oferta["endDate"]),
        })
    return juegos
