import asyncio
import logging
import os
from dotenv import load_dotenv
from telegram import LinkPreviewOptions, Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from epic import date_range, fetch_games


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Registra los errores ocurridos durante el procesamiento de updates."""
    logger.error(msg="Excepción al manejar un update:", exc_info=context.error)

    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ Ocurrió un error inesperado al procesar tu solicitud. Inténtalo más tarde."
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"Hola {update.effective_user.first_name}, ¿quieres ver los juegos gratis de esta semana?\n\n"
        "/gratis - Juegos gratis de esta semana\n"
        "/proximos - Juegos gratis de la semana próxima"
    )



async def eco_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto_usuario = update.message.text
    logger.info(f"Mensaje de texto recibido de {update.effective_user.username}: {texto_usuario}")
    await update.message.reply_text(texto_usuario)


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


def main():
    if not TELEGRAM_TOKEN:
        logger.error("No se encontró el TELEGRAM_TOKEN en el archivo .env")
        return
  
    application = Application.builder().token(TELEGRAM_TOKEN).build()


    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("gratis", gratis))
    application.add_handler(CommandHandler("proximos", proximos))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, eco_handler))

    application.add_error_handler(error_handler)

    logger.info("🤖 EpikFreeBot iniciado correctamente. Ejecutando polling...")
    application.run_polling()


if __name__ == "__main__":
    main()