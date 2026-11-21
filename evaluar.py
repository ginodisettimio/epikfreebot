"""
Evaluación sistemática de EpikFreeBot.

Envía al bot cada pregunta de casos_prueba.json (sin pasar por Telegram) y
evalúa la respuesta con dos criterios:
  1. Herramienta: ¿el modelo usó la función esperada? Se verifica con código.
  2. Contenido: ¿la respuesta cumple el criterio? Lo decide un segundo modelo
     que actúa como evaluador ("LLM como juez"), con salida estructurada.

El resultado se muestra en la terminal y se guarda en resultados_evaluacion.csv.
"""

import asyncio                          # permite ejecutar corrutinas desde un script
import csv                              # escritura del reporte en formato CSV
import json                             # lectura de los casos de prueba

from pydantic import BaseModel, Field   # esquema de la respuesta del evaluador

import bot                              # se reutilizan el cliente y consultar_gemini del bot

RUTA_CASOS = "casos_prueba.json"
RUTA_REPORTE = "resultados_evaluacion.csv"

# Pausa entre casos, en segundos, para no superar la cuota de consultas por minuto.
PAUSA_SEGUNDOS = 6


class Juicio(BaseModel):
    """Respuesta que debe devolver el modelo evaluador."""
    cumple: bool = Field(description="true si la respuesta cumple el criterio; false si no.")
    justificacion: str = Field(description="Explicación breve, en una oración.")


PROMPT_JUEZ = """
Sos un evaluador estricto de un asistente sobre videojuegos y la Epic Games Store.
Recibís una pregunta, la respuesta del asistente y un criterio.
Decidí si la respuesta cumple el criterio. Evaluá solo el criterio indicado,
no el estilo ni la extensión de la respuesta.
""".strip()


async def juzgar(caso: dict, respuesta: str) -> Juicio:
    """Le pide al modelo evaluador que decida si la respuesta cumple el criterio."""
    consulta = (
        f"Pregunta: {caso['pregunta']}\n\n"
        f"Respuesta del asistente: {respuesta}\n\n"
        f"Criterio: {caso['criterio']}"
    )
    interaccion = await bot.cliente_gemini.aio.interactions.create(
        model=bot.GEMINI_MODEL,
        system_instruction=PROMPT_JUEZ,
        input=consulta,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": Juicio.model_json_schema(),
        },
        store=False,
    )
    return Juicio.model_validate_json(interaccion.output_text)


async def evaluar_caso(caso: dict) -> dict:
    """Ejecuta un caso de prueba y devuelve una fila del reporte."""
    herramientas_usadas = []            # consultar_gemini agrega aquí cada función que se pidió
    respuesta = await bot.consultar_gemini(
        [],                             # historial vacío: cada caso es independiente
        [{"type": "text", "text": caso["pregunta"]}],
        registro=herramientas_usadas,
    )

    esperada = caso["herramienta_esperada"]
    if esperada is None:
        herramienta_ok = not herramientas_usadas        # no debía usar ninguna
    else:
        herramienta_ok = esperada in herramientas_usadas

    juicio = await juzgar(caso, respuesta)

    return {
        "pregunta": caso["pregunta"],
        "herramienta_esperada": esperada or "ninguna",
        "herramientas_usadas": ", ".join(herramientas_usadas) or "ninguna",
        "herramienta_ok": herramienta_ok,
        "cumple_criterio": juicio.cumple,
        "justificacion": juicio.justificacion,
        "respuesta": respuesta,
    }


def marca(ok: bool) -> str:
    """Devuelve un símbolo para mostrar un resultado en la terminal."""
    return "✔" if ok else "✘"


async def main():
    with open(RUTA_CASOS, encoding="utf-8") as archivo:
        casos = json.load(archivo)

    filas = []
    for numero, caso in enumerate(casos, start=1):      # enumerate numera desde 1
        fila = await evaluar_caso(caso)
        filas.append(fila)
        print(f"{numero}. {marca(fila['herramienta_ok'])} herramienta "
              f"{marca(fila['cumple_criterio'])} contenido | {caso['pregunta']}")
        if not fila["cumple_criterio"]:
            print(f"   → {fila['justificacion']}")
        await asyncio.sleep(PAUSA_SEGUNDOS)

    # Resumen: sum cuenta los True (True vale 1 y False vale 0).
    total = len(filas)
    ok_herramienta = sum(f["herramienta_ok"] for f in filas)
    ok_contenido = sum(f["cumple_criterio"] for f in filas)
    print(f"\nHerramienta correcta: {ok_herramienta}/{total} ({ok_herramienta / total:.0%})")
    print(f"Criterio cumplido:    {ok_contenido}/{total} ({ok_contenido / total:.0%})")

    # DictWriter escribe una fila por diccionario; las claves son las columnas.
    with open(RUTA_REPORTE, "w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)
    print(f"Reporte guardado en {RUTA_REPORTE}")

asyncio.run(main())
