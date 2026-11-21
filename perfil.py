"""
Perfil de jugador con salida estructurada.

En lugar de pedirle al modelo un texto libre, se le exige una respuesta en
JSON que cumpla un esquema definido con Pydantic. Así el programa puede
guardar cada dato en su propia columna y usarlo para personalizar las
recomendaciones de juegos.
"""

from typing import Literal              # restringe un campo a un conjunto fijo de valores

from pydantic import BaseModel, Field, field_validator   # estructuras y validación


class PerfilUsuario(BaseModel):
    """Estructura que debe tener el perfil de un jugador."""

    # El perfil se identifica con el id de Telegram, que el bot ya conoce:
    # por eso no se pide el teléfono.
    genero: Literal[
        "RPG", "acción", "aventura", "estrategia", "deportes", "carreras",
        "simulación", "disparos", "terror", "puzzle", "plataformas", "lucha",
        "sin especificar",
    ] = Field(
        default="Sin especificar",
        description="Género de videojuego que más le gusta al usuario.",
    )
    juego_favorito: str = Field(
        default="Sin especificar",
        description="Título del juego favorito del usuario.",
    )
    plataforma: Literal[
        "PC", "PlayStation", "Xbox", "Nintendo Switch", "móvil", "sin especificar"
    ] = Field(
        default="Sin especificar",
        description="Plataforma principal en la que juega el usuario.",
    )
    # ge=0 impide valores negativos. 0 significa que no puso un límite.
    precio_maximo: int = Field(
        default=0, 
        ge=0,
        description=(
            "Presupuesto máximo en pesos argentinos para comprar un juego. "
            "Usá 0 si no tiene límite o no lo mencionó."
        ),
    )

    @field_validator("juego_favorito")
    @classmethod
    def _limpiar_juego(cls, valor: str) -> str:
        """Quita espacios sobrantes y evita guardar un campo vacío."""
        return valor.strip() or "sin especificar"


# Instrucciones para esta tarea puntual. Son distintas del prompt de sistema
# de la conversación: aquí el modelo no dialoga, solo extrae datos.
PROMPT_PERFIL = """
Extraés el perfil de un jugador a partir de un texto libre.
Respondé únicamente con el perfil pedido, en español.
Reglas:
- genero: género de videojuego que más le gusta: "RPG", "Acción", "Aventura",
  "Estrategia", "Deportes", "Carreras", "Simulación", "Disparos", "Terror",
  "Puzzle", "Plataformas", "Lucha" o "Sin especificar". Si dice "rol", usá "RPG".
  Si menciona varios, elegí el principal.
- juego_favorito: el título tal como lo escribió el usuario.
- plataforma: "PC", "PlayStation", "Xbox", "Nintendo Switch", "Móvil" o "Sin especificar".
- precio_maximo: presupuesto máximo en pesos argentinos, como número entero.
  Si el usuario no menciona un límite, usá 0.
Si un dato no aparece en el texto, usá "sin especificar" (o 0 en el precio).
No inventes datos que el usuario no escribió.
""".strip()


async def analizar_perfil(cliente, modelo: str, texto: str) -> PerfilUsuario:
    """Envía el texto a Gemini y devuelve el perfil ya validado."""

    interaccion = await cliente.aio.interactions.create(
        model=modelo,
        system_instruction=PROMPT_PERFIL,
        input=texto,
        # response_format exige una respuesta en JSON que respete el esquema.
        # model_json_schema() traduce la clase de Pydantic a JSON Schema.
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": PerfilUsuario.model_json_schema(),
        },
        store=False,
    )

    # model_validate_json convierte el texto JSON en un objeto PerfilUsuario
    # y verifica cada campo. Si el modelo devolviera un precio negativo o una
    # plataforma no permitida, se produce un ValidationError.
    return PerfilUsuario.model_validate_json(interaccion.output_text)


def describir_perfil(perfil: dict) -> str:
    """
    Devuelve el perfil como texto para el prompt del modelo.

    El id de Telegram no se incluye: no aporta nada a la recomendación.
    """
    limite = (
        f"{perfil['precio_maximo']} pesos argentinos"
        if perfil["precio_maximo"]
        else "sin límite definido"
    )
    return (
        "Perfil del usuario (usalo para personalizar las recomendaciones):\n"
        f"- Género de juego favorito: {perfil['genero']}\n"
        f"- Juego favorito: {perfil['juego_favorito']}\n"
        f"- Plataforma principal: {perfil['plataforma']}\n"
        f"- Presupuesto máximo: {limite}"
    )
