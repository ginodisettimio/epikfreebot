"""
Prueba aislada de las herramientas, sin Telegram ni Gemini.
Llama a cada función directamente y muestra lo que devuelve.
"""

import asyncio                          # permite ejecutar corrutinas desde un script
import json                             # para mostrar los resultados con formato legible

from herramientas import ejecutar_funcion, informacion_juego, juegos_gratis, proximos_juegos


async def main():
    # Casos normales: consultan las APIs reales.
    print(json.dumps(await juegos_gratis(), ensure_ascii=False, indent=2))
    print(json.dumps(await proximos_juegos(), ensure_ascii=False, indent=2))
    print(json.dumps(await informacion_juego("Celeste"), ensure_ascii=False, indent=2))

    # Caso sin coincidencias útiles: RAWG tolera la búsqueda difusa, así que
    # devuelve el juego más parecido en lugar de un error.
    print(await informacion_juego("zzzzzzz juego inexistente zzzzzzz"))

    # Caso de error: siempre debe ser un diccionario con la clave "error", no una excepción.
    print(await ejecutar_funcion("funcion_inexistente", {}))


asyncio.run(main())                     # pone en marcha el bucle de eventos
