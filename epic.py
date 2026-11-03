from dotenv import load_dotenv
import os
from datetime import datetime

from epicstore_api import EpicGamesStoreAPI


load_dotenv()
EPIC_LOCALE = os.getenv("EPIC_LOCALE", "es-ES")
EPIC_COUNTRY = os.getenv("EPIC_COUNTRY", "AR")

STORE_URL = f"https://store.epicgames.com/{EPIC_LOCALE}"

api = EpicGamesStoreAPI(locale=EPIC_LOCALE, country=EPIC_COUNTRY)


def _free_offer(promo_groups: list | None) -> dict | None:
    # Devuelve la primera oferta con 100% de descuento (precio 0), o None.
    for group in promo_groups or []:
        for offer in group.get("promotionalOffers") or []:
            if (offer.get("discountSetting") or {}).get("discountPercentage") == 0:
                return offer
    return None


def _game_url(element: dict) -> str:
    mappings = ((element.get("catalogNs") or {}).get("mappings") or []) + (
        element.get("offerMappings") or []
    )
    slug = next((m.get("pageSlug") for m in mappings if m.get("pageSlug")), None)
    slug = slug or element.get("productSlug")
    return f"{STORE_URL}/p/{slug}" if slug else f"{STORE_URL}/free-games"


def _game_price(element: dict) -> str:
    fmt = ((element.get("price") or {}).get("totalPrice") or {}).get("fmtPrice") or {}
    price = fmt.get("originalPrice") or "N/D"
    return "Free-to-play" if price == "0" else price


def _fmt_date(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d/%m/%Y")


def fetch_games(kind: str) -> list[dict]:
    # kind: 'current' (gratis ahora) o 'upcoming' (gratis próximamente).
    key = "promotionalOffers" if kind == "current" else "upcomingPromotionalOffers"
    data = api.get_free_games()
    elements = data["data"]["Catalog"]["searchStore"]["elements"]

    games = []
    for el in elements:
        offer = _free_offer((el.get("promotions") or {}).get(key))
        if offer is None:
            continue
        games.append({
            "title": el.get("title", "Sin nombre"),
            "url": _game_url(el),
            "price": _game_price(el),
            "start": offer["startDate"],
            "end": offer["endDate"],
        })
    return games


def date_range(games: list[dict]) -> str:
    return f"{_fmt_date(games[0]['start'])} - {_fmt_date(games[0]['end'])}"
