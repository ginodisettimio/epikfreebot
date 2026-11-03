from dotenv import load_dotenv
import asyncio
import os

from telegram import LinkPreviewOptions, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from epic import date_range, fetch_games


load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"Hola {update.effective_user.first_name}, ¿quieres ver los juegos gratis de esta semana?\n"
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
    lines += [f"{i}. {g['title']} - {g['url']} - {g['price']}" for i, g in enumerate(games, 1)]
    await update.message.reply_text("\n".join(lines), link_preview_options=NO_PREVIEW)


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
    lines += [f"{i}. {g['title']} - {g['url']} - {g['price']}" for i, g in enumerate(games, 1)]
    await update.message.reply_text("\n".join(lines), link_preview_options=NO_PREVIEW)


if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gratis", gratis))
    app.add_handler(CommandHandler("proximos", proximos))
    app.run_polling()
