"""
Herramientas de EpikFreeBot: funciones que el modelo puede pedir que se ejecuten.

El módulo tiene tres partes:
  1. Las funciones propiamente dichas: dos consultan la Epic Games Store
     (a través de epic.py) y una consulta la API de RAWG con httpx.
  2. Las declaraciones: la descripción de cada función en JSON Schema,
     que es lo único que el modelo ve de ellas.
  3. Un despachador que ejecuta la función pedida por el modelo.
"""

import asyncio                        # para ejecutar funciones bloqueantes en un hilo aparte
import logging                        # registro de eventos en la terminal
import os                             # para leer las variables del .env
from datetime import datetime         # para pasar las fechas ISO a formato corto

import httpx                          # cliente HTTP asíncrono
from dotenv import load_dotenv

from epic import date_range, fetch_games

load_dotenv()
logger = logging.getLogger("epikfreebot")   # mismo registrador que bot.py

# Clave de la API de RAWG. Sin ella la consulta no se puede hacer (la API
# responde 401), y la función lo informa como dato en lugar de fallar.
RAWG_API_KEY = os.getenv("RAWG_API_KEY", "").strip()

# Tiempo máximo de espera de cada consulta HTTP, en segundos. Sin un límite,
# una API que no responde dejaría al usuario esperando indefinidamente.
TIEMPO_ESPERA = 10

# URL base de la API de RAWG y límite de caracteres de la descripción que se
# devuelve al modelo: más texto solo consume contexto sin aportar.
URL_RAWG = "https://api.rawg.io/api"
LIMITE_DESCRIPCION = 600


# ---------------------------------------------------------------------------
# 1. Funciones
# ---------------------------------------------------------------------------

def _fecha_corta(iso: str) -> str:
    """Convierte una fecha ISO ('2026-11-13T15:00:00.000Z') en '13/11/2026'."""
    # fromisoformat entiende el formato de la Epic Store; la Z de UTC se
    # reemplaza por el desplazamiento horario que Python sí reconoce.
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d/%m/%Y")


def _armar_juegos(games: list[dict]) -> list[dict]:
    """Pasa la lista cruda de epic.py a un formato breve y legible para el modelo."""
    return [
        {
            "titulo": g["title"],
            "url": g["url"],
            "precio_normal": g["price"],
            "inicio": _fecha_corta(g["start"]),
            "fin": _fecha_corta(g["end"]),
        }
        for g in games
    ]


async def juegos_gratis() -> dict:
    """Devuelve los juegos que Epic regala ahora mismo (gratis esta semana)."""
    # fetch_games es síncrona (usa requests por dentro): asyncio.to_thread la
    # ejecuta en un hilo de trabajo para no bloquear el bot mientras espera.
    try:
        games = await asyncio.to_thread(fetch_games, "current")
    except Exception as error:
        # El error se devuelve como dato, no como excepción: así el modelo
        # puede explicárselo al usuario sin que el ciclo de herramientas se corte.
        return {"error": f"No se pudo consultar la Epic Games Store: {type(error).__name__}"}

    if not games:
        return {"mensaje": "Esta semana Epic no está regalando juegos."}

    return {
        "periodo": date_range(games),     # '13/11/2026 - 20/11/2026'
        "cantidad": len(games),
        "juegos": _armar_juegos(games),
    }


async def proximos_juegos() -> dict:
    """Devuelve los juegos que Epic va a regalar en la próxima semana."""
    try:
        games = await asyncio.to_thread(fetch_games, "upcoming")
    except Exception as error:
        return {"error": f"No se pudo consultar la Epic Games Store: {type(error).__name__}"}

    if not games:
        return {"mensaje": "Todavía no se conocen los juegos gratis de la semana próxima."}

    return {
        "periodo": date_range(games),
        "cantidad": len(games),
        "juegos": _armar_juegos(games),
    }


async def informacion_juego(juego: str) -> dict:
    """Busca un juego en RAWG y devuelve su ficha: fecha, género, nota y plataformas."""
    if not RAWG_API_KEY:
        return {
            "error": "No hay clave de RAWG configurada en el archivo .env (RAWG_API_KEY).",
            "como_resolverlo": "Crear una cuenta gratuita en https://rawg.io/apidocs y pegar la clave.",
        }

    # "async with" abre el cliente HTTP y lo cierra al terminar el bloque.
    async with httpx.AsyncClient(timeout=TIEMPO_ESPERA) as cliente_http:
        # Búsqueda por nombre: el parámetro "search" hace coincidencia parcial.
        busqueda = await cliente_http.get(
            f"{URL_RAWG}/games",
            params={"key": RAWG_API_KEY, "search": juego, "page_size": 5},
        )
        busqueda.raise_for_status()   # convierte un código HTTP de error en excepción
        resultados = busqueda.json().get("results") or []

        if not resultados:
            # El error se devuelve como dato: el modelo lo explica y ofrece alternativas.
            return {"error": f"No encontré juegos que coincidan con: {juego}"}

        # El primer resultado es el que más coincide con lo que escribió el usuario.
        primero = resultados[0]

        # Ficha completa: la búsqueda no trae la descripción, así que se pide
        # el detalle por id. Si esta segunda consulta falla, se devuelve igual
        # lo que ya se tiene (aviso en lugar de perder todo el resultado).
        aviso = ""
        try:
            detalle = await cliente_http.get(
                f"{URL_RAWG}/games/{primero['id']}",
                params={"key": RAWG_API_KEY},
            )
            detalle.raise_for_status()
            ficha = detalle.json()
        except httpx.HTTPError as error:
            ficha = primero
            aviso = f"No pude ampliar la ficha: {type(error).__name__}"

    # description_raw es la versión sin etiquetas HTML de la descripción.
    descripcion = (ficha.get("description_raw") or "").strip()
    if len(descripcion) > LIMITE_DESCRIPCION:
        descripcion = descripcion[:LIMITE_DESCRIPCION].rstrip() + "…"

    # Solo nombres: los ids de RAWG (géneros y plataformas) no le sirven al modelo.
    generos = [g.get("name") for g in ficha.get("genres") or [] if g.get("name")]
    plataformas = [p.get("platform", {}).get("name")
                   for p in ficha.get("platforms") or []
                   if (p.get("platform") or {}).get("name")]

    resultado = {
        "titulo": ficha.get("name"),
        "fecha_lanzamiento": ficha.get("released") or "sin confirmar",
        "en_desarrollo": bool(ficha.get("tba")),
        "nota_usuarios": ficha.get("rating"),          # promedio sobre 5
        "metacritic": ficha.get("metacritic"),         # sobre 100, puede ser null
        "generos": generos,
        "plataformas": plataformas,
        "desarrollador": ((ficha.get("developers") or [{}])[0]).get("name"),
        "descripcion": descripcion or "Sin descripción disponible.",
        "url": ficha.get("website") or (
            f"https://rawg.io/games/{ficha['slug']}" if ficha.get("slug") else "sin enlace"
        ),
    }

    # Otros títulos que también coinciden con la búsqueda, por si el primero
    # no es el juego que el usuario tenía en mente.
    otros = [
        {"titulo": r.get("name"), "id": r.get("id")}
        for r in resultados[1:4]
        if r.get("name")
    ]
    if otros:
        resultado["otras_coincidencias"] = otros
    if aviso:
        resultado["aviso"] = aviso
    return resultado


# ---------------------------------------------------------------------------
# 2. Declaraciones para el modelo
# ---------------------------------------------------------------------------

# Esto es lo único que Gemini conoce de cada función: su nombre, para qué sirve
# y qué parámetros recibe, descriptos con JSON Schema. La calidad de las
# descripciones determina si el modelo elige bien la función y sus argumentos.
DECLARACIONES = [
    {
        "type": "function",
        "name": "juegos_gratis",
        "description": (
            "Obtiene los juegos que la Epic Games Store está regalando en este momento, "
            "con sus títulos, enlaces, precios normales y fechas de la promoción. "
            "Usala cuando el usuario pregunte por los juegos gratis de esta semana o por "
            "lo que se puede reclamar ahora mismo. Nunca inventes títulos ni enlaces."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "proximos_juegos",
        "description": (
            "Obtiene los juegos que la Epic Games Store va a regalar en la próxima semana, "
            "aún no disponibles. Usala cuando el usuario pregunte por los próximos juegos "
            "gratis o qué se viene la semana que viene."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "informacion_juego",
        "description": (
            "Busca un juego en la base de datos de RAWG y devuelve su ficha: fecha de "
            "lanzamiento, géneros, plataformas, desarrollador, nota de usuarios, Metacritic "
            "y descripción. Usala cuando el usuario pida detalles sobre un juego en "
            "particular, o para recomendar títulos parecidos a los de Epic."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "juego": {
                    "type": "string",
                    "description": "Nombre del juego tal como lo escribió el usuario.",
                },
            },
            "required": ["juego"],
        },
    },
]


# ---------------------------------------------------------------------------
# 3. Despachador
# ---------------------------------------------------------------------------

# Relaciona el nombre que usa el modelo con la función de Python que se ejecuta.
FUNCIONES = {
    "juegos_gratis": juegos_gratis,
    "proximos_juegos": proximos_juegos,
    "informacion_juego": informacion_juego,
}


async def ejecutar_funcion(nombre: str, argumentos: dict) -> dict:
    """Ejecuta la función pedida por el modelo y devuelve siempre un diccionario."""
    logger.info("El modelo pidió %s(%s)", nombre, argumentos)

    funcion = FUNCIONES.get(nombre)
    if funcion is None:                 # el modelo pidió una función que no existe
        return {"error": f"Función desconocida: {nombre}"}

    try:
        # **argumentos desempaqueta el diccionario como parámetros con nombre:
        # {"juego": "Celeste"} se convierte en informacion_juego(juego="Celeste").
        return await funcion(**argumentos)
    except Exception as error:
        # Cualquier falla (API caída, argumentos inválidos, tiempo agotado) se
        # informa al modelo como dato, para que pueda responder al usuario.
        logger.exception("Falló la herramienta %s", nombre)
        return {"error": f"No se pudo obtener el dato: {type(error).__name__}"}
