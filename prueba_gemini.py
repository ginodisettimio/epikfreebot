"""
Prueba aislada de la conexión con Gemini.
Se ejecuta una sola vez, antes de modificar el bot, para confirmar que la
clave de API y el modelo funcionan.
"""

import os                              # acceso a las variables de entorno

from dotenv import load_dotenv         # lee el archivo .env
from google import genai               # SDK oficial de Gemini (google-genai)

# Carga en el entorno las variables definidas en .env
# (TELEGRAM_TOKEN, GEMINI_API_KEY y GEMINI_MODEL).
load_dotenv()

# Se crea el cliente con la clave leída del entorno.
# Si la clave falta o es inválida, el error aparece en la llamada siguiente.
cliente = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Se envía una única consulta. Esta versión es síncrona (sin await):
# en un script de prueba no hay otros usuarios que atender.
interaccion = cliente.interactions.create(
    model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),  # modelo del .env o el valor por defecto
    input="Recomendame una bodega en Luján de Cuyo, en una sola oración.",
    store=False,                       # Google no conserva la interacción
)

# output_text contiene el texto generado por el modelo.
print(interaccion.output_text)
