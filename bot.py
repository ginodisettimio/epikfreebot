import asyncio
import json                             # convierte los resultados de las funciones a texto JSON
import logging
import os

from dotenv import load_dotenv
from google import genai
from pydantic import ValidationError    # error que se produce si el JSON no cumple el esquema

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
from herramientas import DECLARACIONES, ejecutar_funcion   # funciones propias del bot
from perfil import analizar_perfil, describir_perfil       # perfil estructurado del jugador
from prompts import PROMPT_SISTEMA
from epic import obtener_juegos, rango_fechas


load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
MAX_MENSAJES_HISTORIAL = os.getenv("MAX_MENSAJES_HISTORIAL", 20)

# Cantidad máxima de vueltas del ciclo de function calling en un mismo mensaje.
# Evita un bucle infinito si el modelo pidiera funciones una y otra vez.
MAX_VUELTAS_HERRAMIENTAS = 5

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
        "Escribe /ayuda para ver mis comandos. Si querés recomendaciones a tu "
        "medida, creá tu perfil con /perfil."
    )


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"Mis comandos son:\n"
        "/start - Comenzar la conversación\n"
        "/ayuda - Esta ayuda\n"
        "/olvidar - Borra nuestra conversación y empezar de cero\n"
        "/perfil <texto> - Creá o actualizá tu perfil de jugador\n"
        "/yo - Ver tu perfil\n"
        "/gratis - Juegos gratis de esta semana\n"
        "/proximos - Juegos gratis de la semana próxima\n"
        "También puedo darte información de juegos concretos (fecha, género, "
        "plataformas y nota) y recomendarte según tu perfil."
    )
    

async def gratis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Devuelve la lista de juegos gratis semanal"""
    try:
        juegos = await asyncio.to_thread(obtener_juegos, "actuales")
    except Exception:
        await update.message.reply_text("No pude consultar la Epic Games Store, intenta más tarde.")
        return

    if not juegos:
        await update.message.reply_text("Esta semana Epic no está regalando juegos.")
        return

    lineas = [f"Esta semana ({rango_fechas(juegos)}). Epic regala:"]
    lineas += [
        f"{i}. {juego['titulo']} - {juego['url']}\n{juego['precio_normal']}"
        for i, juego in enumerate(juegos, 1)
    ]

    await update.message.reply_text(
        "\n".join(lineas),
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )


async def proximos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Devuelve la lista de juegos gratis de la próxima semana"""
    try:
        juegos = await asyncio.to_thread(obtener_juegos, "proximos")
    except Exception:
        await update.message.reply_text("No pude consultar la Epic Games Store, intenta más tarde.")
        return

    if not juegos:
        await update.message.reply_text("Todavía no se conocen los juegos gratis de la semana próxima.")
        return

    lineas = [f"La semana próxima ({rango_fechas(juegos)}). Epic regalará:"]
    lineas += [
        f"{i}. {juego['titulo']} - {juego['url']}\n{juego['precio_normal']}"
        for i, juego in enumerate(juegos, 1)
    ]

    await update.message.reply_text(
        "\n".join(lineas),
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )


async def olvidar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Borra el historial del usuario."""
    borrados = await db.borrar_historial(update.effective_user.id)
    logger.info("Usuario %s borró %d mensajes", update.effective_user.id, borrados)
    await update.message.reply_text("Listo, empezamos de cero. ¿En qué te puedo ayudar?")


async def perfil(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /perfil: analiza el texto y guarda el perfil."""
    # context.args contiene las palabras escritas después del comando,
    # separadas por espacios: "/perfil Hola soy Ana" → ["Hola", "soy", "Ana"].
    texto = " ".join(context.args).strip()
    if not texto:
        await update.message.reply_text(
            "Contame tu perfil en una frase. Por ejemplo:\n"
            "/perfil Me gustan los RPG, mi juego favorito es Stardew Valley, "
            "juego en PC y puedo gastar hasta 20000 pesos."
        )
        return

    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        datos = await analizar_perfil(cliente_gemini, GEMINI_MODEL, texto)
    except ValidationError:
        # El modelo respondió, pero el JSON no cumple el esquema.
        logger.exception("Perfil con formato inválido")
        await update.message.reply_text("No pude interpretar tu perfil. ¿Probás escribirlo de nuevo? 🙏")
        return
    except Exception as error:
        logger.exception("Error al analizar el perfil")
        await update.message.reply_text(describir_error(error))
        return

    await db.guardar_perfil(update.effective_user.id, datos)

    # El análisis es un objeto: sus campos se usan directamente, sin interpretar texto.
    await update.message.reply_text(
        "¡Listo! Guardé tu perfil 🎮\n\n"
        f"Género de juego: {datos.genero}\n"
        f"Juego favorito: {datos.juego_favorito}\n"
        f"Plataforma: {datos.plataforma}\n"
        f"Precio máximo: {datos.precio_maximo} ARS\n\n"
        "A partir de ahora tengo en cuenta estos datos para recomendarte juegos. "
        "Podés actualizarlo cuando quieras con /perfil."
    )


async def yo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /yo: muestra el perfil del usuario."""
    datos = await db.obtener_perfil(update.effective_user.id)
    if datos is None:
        await update.message.reply_text(
            "Todavía no tengo tu perfil. Podés crearlo con /perfil."
        )
        return

    limite = (
        f"{datos['precio_maximo']} ARS"
        if datos["precio_maximo"]
        else "sin límite definido"
    )
    await update.message.reply_text(
        "Tu perfil 🎮\n\n"
        f"Género de juego: {datos['genero']}\n"
        f"Juego favorito: {datos['juego_favorito']}\n"
        f"Plataforma: {datos['plataforma']}\n"
        f"Precio máximo: {limite}"
    )


async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde con Gemini, teniendo en cuenta la conversación previa."""
    user_id = update.effective_user.id                  # identifica de quién es la conversación
    texto = update.message.text
    logger.info("Mensaje de %s: %s", user_id, texto)

    await update.message.chat.send_action(ChatAction.TYPING)

    # Paso 1: recuperar lo que ya se habló con este usuario.
    historial = await db.obtener_historial(user_id, MAX_MENSAJES_HISTORIAL)

    # Paso 2: recuperar el perfil, si existe, para personalizar la respuesta.
    perfil_usuario = await db.obtener_perfil(user_id)

    # Paso 3: consultar al modelo con el historial, el mensaje nuevo y el perfil.
    try:
        respuesta = await consultar_gemini(historial, texto, perfil_usuario)
    except Exception as error:
        logger.exception("Error al consultar a Gemini")
        await update.message.reply_text(describir_error(error))
        # Si la consulta falló, no se guarda nada: así el historial nunca
        # queda con una pregunta sin su respuesta.
        return

    # Paso 4: guardar la pregunta y la respuesta para la próxima consulta.
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


async def consultar_gemini(
    historial: list[tuple[str, str]],
    mensaje: str,
    perfil: dict | None = None,
) -> str:
    """
    Envía la conversación a Gemini y resuelve el ciclo de function calling:
    mientras el modelo pida funciones, se ejecutan y se le devuelven los
    resultados; cuando responde con texto, se devuelve ese texto.

    Si el usuario tiene un perfil, se agrega al prompt de sistema para que el
    modelo tenga en cuenta sus preferencias al recomendar.
    """
    # Lista de pasos que se envía al modelo. Empieza con el historial y el
    # mensaje nuevo, y crece dentro de este turno con los pedidos de funciones
    # y sus resultados. Esos pasos intermedios no se guardan en la base.
    entrada = armar_entrada(historial, mensaje)

    # El prompt de sistema se completa con el perfil del usuario, si lo tiene.
    instruccion = PROMPT_SISTEMA
    if perfil:
        instruccion = f"{instruccion}\n\n{describir_perfil(perfil)}"

    for vuelta in range(MAX_VUELTAS_HERRAMIENTAS):
        interaccion = await cliente_gemini.aio.interactions.create(
            model=GEMINI_MODEL,
            system_instruction=instruccion,
            input=entrada,
            tools=DECLARACIONES,        # funciones que el modelo puede pedir
            store=False,
        )

        # Pasos de tipo function_call: el modelo pide ejecutar una función.
        # Puede pedir más de una en la misma respuesta (por ejemplo, gratis y RAWG).
        llamadas = [paso for paso in interaccion.steps if paso.type == "function_call"]

        if not llamadas:
            # Sin pedidos de funciones: el modelo ya redactó la respuesta final.
            return interaccion.output_text or "No se me ocurrió nada para responder."

        # Se agregan a la entrada TODOS los pasos que devolvió el modelo, sin
        # modificarlos (incluidos los de razonamiento interno). La API los
        # necesita para relacionar cada resultado con su pedido.
        for paso in interaccion.steps:
            entrada.append(paso.model_dump())

        # Se ejecuta cada función pedida y se agrega su resultado como un paso
        # function_result. call_id debe coincidir con el id del pedido.
        for llamada in llamadas:
            resultado = await ejecutar_funcion(llamada.name, llamada.arguments)
            entrada.append({
                "type": "function_result",
                "call_id": llamada.id,
                "name": llamada.name,
                # ensure_ascii=False conserva tildes y ñ en lugar de códigos \u00f1
                "result": [{"type": "text", "text": json.dumps(resultado, ensure_ascii=False)}],
            })
        # Se repite el ciclo: el modelo recibe los resultados y decide si
        # necesita otra función o si ya puede responder.

    # Se agotaron las vueltas sin respuesta final.
    logger.warning("Se alcanzó el máximo de %d vueltas de herramientas", MAX_VUELTAS_HERRAMIENTAS)
    return "No pude completar la consulta. ¿Podés reformular la pregunta?"


def describir_error(error: Exception) -> str:
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


async def al_fallar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Manejador de errores de python-telegram-bot: se activa cuando una excepción
    se escapa de un manejador. Registra la traza completa y avisa al usuario
    si el error ocurrió dentro de una conversación.
    """
    # El error que provocó la falla viene en context.error; exc_info hace que
    # el registrador imprima la traza completa, no solo el mensaje.
    error = context.error
    logger.error("Error no controlado en el bot: %s", error, exc_info=error)

    # update puede ser None si el error no se originó en un mensaje concreto.
    mensaje = update.effective_message if update else None
    if mensaje is not None:
        await mensaje.reply_text(describir_error(error))


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
    application.add_handler(CommandHandler("ayuda", ayuda))
    application.add_handler(CommandHandler("olvidar", olvidar))
    application.add_handler(CommandHandler("perfil", perfil))
    application.add_handler(CommandHandler("yo", yo))
    application.add_handler(CommandHandler("gratis", gratis))
    application.add_handler(CommandHandler("proximos", proximos))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    application.add_error_handler(al_fallar)

    logger.info("Epikfreebot v5 en línea con el modelo %s.", GEMINI_MODEL)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
