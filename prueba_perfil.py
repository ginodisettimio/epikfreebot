"""
Prueba aislada del análisis de perfiles: consulta a Gemini sin pasar por Telegram.
"""

import asyncio                          # permite ejecutar corrutinas desde un script
import os                               # acceso a las variables de entorno

from dotenv import load_dotenv          # lee el archivo .env
from google import genai                # SDK oficial de Gemini

from perfil import analizar_perfil      # la función que se quiere probar

load_dotenv()
cliente = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
modelo = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")


async def main():
    textos = [
        "Me gustan los RPG, mi juego favorito es Elden Ring, juego en PC y "
        "puedo gastar hasta 30000 pesos.",
        "Soy Lucía. Me encanta Zelda, juego en Nintendo Switch. No tengo "
        "límite de precio.",
        "Hola, me llamo Pedro. Juego en PlayStation, mi juego favorito es "
        "God of War y me gustan los juegos de acción.",
        "Me gustan la estrategia y los puzzles, pero todavía no tengo un "
        "juego favorito.",
    ]
    for texto in textos:
        perfil = await analizar_perfil(cliente, modelo, texto)
        # perfil es un objeto: sus campos se leen como atributos.
        print(perfil.model_dump())

asyncio.run(main())
