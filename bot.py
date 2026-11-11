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

import db
from prompts import PROMPT_SISTEMA
from epic import date_range, fetch_games


load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
MAX_MENSAJES_HISTORIAL = os.getenv("MAX_MENSAJES_HISTORIAL", 20)

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
        "/start - Comenzar la conversación\n"
        "/help - Esta ayuda\n"
        "/olvidar - Borra nuestra conversación y empezar de cero\n"
        "/gratis - Juegos gratis de esta semana\n"
        "/proximos - Juegos gratis de la semana próxima\n"
        "También brindo información sobre juegos que esten en la tienda de Epic Games."
    )
    

async def gratis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Devuelve la lista de juegos gratis semanal"""
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
    """Devuelve la lista de juegos gratis de la próxima semana"""
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


async def olvidar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Borra el historial del usuario."""
    borrados = await db.borrar_historial(update.effective_user.id)
    logger.info("Usuario %s borró %d mensajes", update.effective_user.id, borrados)
    await update.message.reply_text("Listo, empezamos de cero. ¿En qué te puedo ayudar?")


async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde con Gemini, teniendo en cuenta la conversación previa."""
    user_id = update.effective_user.id                  # identifica de quién es la conversación
    texto = update.message.text
    logger.info("Mensaje de %s: %s", user_id, texto)

    await update.message.chat.send_action(ChatAction.TYPING)

    # Paso 1: recuperar lo que ya se habló con este usuario.
    historial = await db.obtener_historial(user_id, MAX_MENSAJES_HISTORIAL)

    # Paso 2: consultar al modelo con el historial más el mensaje nuevo.
    try:
        respuesta = await consultar_gemini(historial, texto)
    except Exception as error:
        logger.error("Error al consultar a Gemini: %s", error)
        await update.message.reply_text(describir_error(error))
        # Si la consulta falló, no se guarda nada: así el historial nunca
        # queda con una pregunta sin su respuesta.
        return

    # Paso 3: guardar la pregunta y la respuesta para la próxima consulta.
    await db.guardar_intercambio(user_id, texto, respuesta)

    for inicio in range(0, len(respuesta), LIMITE_TELEGRAM):
        await update.message.reply_text(respuesta[inicio:inicio + LIMITE_TELEGRAM])


def armar_entrada(historial: list[tuple[str, str]], mensaje_nuevo: str) -> list[dict]:
    """
    Convierte el historial guardado en la lista de pasos (steps) que espera
    la Interactions API y agrega al final el mensaje nuevo del usuario.
    """
    # Equivalencia entre el rol guardado en la base y el tipo de paso de la API.
    tipo_de_paso = {"user": "user_input", "model": "model_output"}

    # Lista por comprensión: un diccionario por cada fila del historial.
    # Cada paso indica su tipo y su contenido, que es una lista de bloques;
    # aquí, un único bloque de texto.
    pasos = [
        {"type": tipo_de_paso[rol], "content": [{"type": "text", "text": texto}]}
        for rol, texto in historial
    ]

    # El último paso es siempre el mensaje que el usuario acaba de enviar.
    pasos.append({"type": "user_input", "content": [{"type": "text", "text": mensaje_nuevo}]})
    return pasos


async def consultar_gemini(historial: list[tuple[str, str]], mensaje: str) -> str:
    """Envía a Gemini la conversación completa y devuelve el texto de la respuesta."""
    interaccion = await cliente_gemini.aio.interactions.create(
        model=GEMINI_MODEL,
        system_instruction=PROMPT_SISTEMA,
        input=armar_entrada(historial, mensaje),  # conversación completa, no solo el último texto
        store=False,                              # la memoria la administra el bot, no Google
    )

    return interaccion.output_text or "No se me ocurrió nada para responder."


def describir_error(error: Exception, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Traduce un error de la API a un mensaje comprensible para el usuario."""

    # Los errores HTTP de la API traen el código en el atributo status_code.
    # getattr devuelve None si el error no tiene ese atributo (por ejemplo,
    # una falla de red sin respuesta del servidor).
    codigo = getattr(error, "status_code", None)

    if codigo == 429:                   # 429: se superó la cuota de consultas
        return "Estoy recibiendo demasiadas consultas. Prueba de nuevo en un minuto, por favor."
    elif codigo in (401, 403):            # 401/403: clave inválida o sin permiso
        return "Tengo un problema de configuración. Contacta con el creador."
    elif codigo == 503:
        return "No encontré información sobre eso."
    # Cualquier otro caso: falla de red, error del servicio, modelo inexistente.
    return "Tuve un problema para pensar la respuesta. ¿Me lo puedes preguntar de nuevo?"


async def al_iniciar(app: Application) -> None:
    """Se ejecuta una sola vez, antes de comenzar a recibir mensajes."""
    # Es una corrutina porque inicializar la base requiere await;
    # por eso no puede llamarse directamente desde main(), que es síncrona.
    await db.inicializar()
    logger.info("Base de datos lista (%s).", db.RUTA_DB)


def main() -> None:
    # Lista con los nombres de las variables obligatorias que faltan en el .env.
    faltantes = [nombre for nombre, valor in [("TELEGRAM_TOKEN", TELEGRAM_TOKEN),
                                              ("GEMINI_API_KEY", GEMINI_API_KEY)]
                 if not valor]
    if faltantes:
        # SystemExit termina el programa mostrando el mensaje indicado.
        raise SystemExit(f"Faltan variables en el .env: {', '.join(faltantes)}")
  
    application = Application.builder().token(TELEGRAM_TOKEN).post_init(al_iniciar).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help))
    application.add_handler(CommandHandler("olvidar", olvidar))
    application.add_handler(CommandHandler("gratis", gratis))
    application.add_handler(CommandHandler("proximos", proximos))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    application.add_error_handler(describir_error)

    logger.info("Epikfreebot v3 en línea con el modelo %s.", GEMINI_MODEL)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
