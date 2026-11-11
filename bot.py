import asyncio
import logging
import os

from dotenv import load_dotenv
from google import genai

from telegram import LinkPreviewOptions, Update
from telegram.constants import ChatAction 
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from prompts import PROMPT_SISTEMA
from epic import date_range, fetch_games


load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
# Registrador propio del bot.
logger = logging.getLogger("epikfreebot")
# Longitud máxima de un mensaje de Telegram, en caracteres.
LIMITE_TELEGRAM = 4096

# Se crea un único cliente para todo el programa. El cliente guarda la clave
# de API y administra las conexiones HTTP con los servidores de Google.
# Crearlo una sola vez evita abrir una conexión nueva en cada mensaje.
cliente_gemini = genai.Client(api_key=GEMINI_API_KEY)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"Hola {update.effective_user.first_name},"
        "¿quieres ver los juegos gratis de esta semana?\n"
        "Escribe /help para ver mis comandos"
    )

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"Mis comandos son:\n"
        "/gratis - Juegos gratis de esta semana\n"
        "/proximos - Juegos gratis de la semana próxima"
    )
    
async def gratis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        games = await asyncio.to_thread(fetch_games, "current")
    except Exception:
        await update.message.reply_text("No pude consultar la Epic Games Store, intenta más tarde.")
        return

    if not games:
        await update.message.reply_text("Esta semana Epic no está regalando juegos.")
        return

    lines = [f"Esta semana ({date_range(games)}). Epic regala:"]
    lines += [f"{i}. {g['title']} - {g['url']}\n{g['price']}" for i, g in enumerate(games, 1)]
    
    
    await update.message.reply_text(
        "\n".join(lines), 
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )


async def proximos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        games = await asyncio.to_thread(fetch_games, "upcoming")
    except Exception:
        await update.message.reply_text("No pude consultar la Epic Games Store, intenta más tarde.")
        return

    if not games:
        await update.message.reply_text("Todavía no se conocen los juegos gratis de la semana próxima.")
        return

    lines = [f"La semana próxima ({date_range(games)}). Epic regalará:"]
    lines += [f"{i}. {g['title']} - {g['url']}\n{g['price']}" for i, g in enumerate(games, 1)]
    
    await update.message.reply_text(
        "\n".join(lines), 
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde cualquier mensaje de texto usando Gemini."""
    texto = update.message.text                         # texto enviado por el usuario
    logger.info("Mensaje de %s: %s", update.effective_user.id, texto)

    # Muestra "escribiendo..." en el chat. La indicación dura unos segundos
    # o hasta que el bot envía su respuesta.
    await update.message.chat.send_action(ChatAction.TYPING)

    # La consulta a una API externa puede fallar por causas ajenas al código;
    # try/except evita que el error llegue al usuario como silencio.
    try:
        respuesta = await consultar_gemini(texto)
    except Exception as error:
        logger.exception("Error al consultar a Gemini")    # detalle técnico, para el desarrollador
        await update.message.reply_text(describir_error(error))  # mensaje amable, para el usuario
        return                                                   # se termina el handler

    # Si la respuesta supera el límite de Telegram, se envía en partes.
    # range(0, len, LIMITE) produce 0, 4096, 8192, ...: el inicio de cada parte.
    for inicio in range(0, len(respuesta), LIMITE_TELEGRAM):
        await update.message.reply_text(respuesta[inicio:inicio + LIMITE_TELEGRAM])

async def consultar_gemini(mensaje: str) -> str:
    """Envía un mensaje a Gemini y devuelve el texto de la respuesta."""

    # .aio accede a la versión asíncrona del cliente; por eso la llamada
    # lleva await. Mientras se espera la respuesta, el bucle de eventos
    # puede atender los mensajes de otros usuarios.
    interaccion = await cliente_gemini.aio.interactions.create(
        model=GEMINI_MODEL,                 # nombre del modelo, leído del .env
        system_instruction=PROMPT_SISTEMA,  # personalidad y reglas de Malbi
        input=mensaje,                      # texto enviado por el usuario
        store=False,                        # Google no conserva la interacción
    )

    # output_text contiene el texto generado por el modelo. Si llega vacío
    # (None o ""), el operador "or" devuelve el mensaje alternativo para que
    # el bot nunca envíe una respuesta en blanco.
    return interaccion.output_text or "No se me ocurrió nada para responder."

def describir_error(error: Exception) -> str:
    """Traduce un error de la API a un mensaje comprensible para el usuario."""

    # Los errores HTTP de la API traen el código en el atributo status_code.
    # getattr devuelve None si el error no tiene ese atributo (por ejemplo,
    # una falla de red sin respuesta del servidor).
    codigo = getattr(error, "status_code", None)

    if codigo == 429:                   # 429: se superó la cuota de consultas
        return "Estoy recibiendo demasiadas consultas. Prueba de nuevo en un minuto, por favor."
    if codigo in (401, 403):            # 401/403: clave inválida o sin permiso
        return "Tengo un problema de configuración."
    # Cualquier otro caso: falla de red, error del servicio, modelo inexistente.
    return "Tuve un problema para pensar la respuesta. ¿Me lo puedes preguntar de nuevo?"


def main() -> None:
    # Lista con los nombres de las variables obligatorias que faltan en el .env.
    faltantes = [nombre for nombre, valor in [("TELEGRAM_TOKEN", TELEGRAM_TOKEN),
                                              ("GEMINI_API_KEY", GEMINI_API_KEY)]
                 if not valor]
    if faltantes:
        # SystemExit termina el programa mostrando el mensaje indicado.
        raise SystemExit(f"Faltan variables en el .env: {', '.join(faltantes)}")
  
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help))
    application.add_handler(CommandHandler("gratis", gratis))
    application.add_handler(CommandHandler("proximos", proximos))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    application.add_error_handler(describir_error)

    logger.info("Epikfreebot v2 en línea con el modelo %s.", GEMINI_MODEL)
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
