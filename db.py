"""
Memoria: historial de conversación y perfiles de jugador en SQLite.

Cada mensaje (del usuario o del modelo) se guarda como una fila de la tabla
`mensajes`, y cada jugador tiene una fila en la tabla `perfiles`. Se utiliza
aiosqlite, la versión asíncrona de sqlite3, para que las operaciones sobre la
base no bloqueen al bot mientras atiende a otros usuarios.
"""

import aiosqlite                        # SQLite con soporte para async/await
import logging                          # registro de eventos en la terminal

logger = logging.getLogger("epikfreebot")   # mismo registrador que bot.py

# Nombre del archivo de la base de datos. Se crea en la carpeta desde la que
# se ejecuta el bot (la raíz del proyecto). Está excluido por .gitignore (*.db).
RUTA_DB = "epikfreebot.db"

# Sentencias SQL que definen la estructura de la base.
# IF NOT EXISTS hace que puedan ejecutarse en cada arranque sin error.
ESQUEMA = """
CREATE TABLE IF NOT EXISTS mensajes (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,      -- número correlativo: orden de llegada
    user_id  INTEGER NOT NULL,                       -- id de Telegram: separa a cada usuario
    rol      TEXT    NOT NULL CHECK (rol IN ('user', 'model')),  -- quién escribió
    texto    TEXT    NOT NULL,                       -- contenido del mensaje
    fecha    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP          -- fecha y hora de guardado
);
-- Índice que acelera la búsqueda de los mensajes de un usuario en orden.
CREATE INDEX IF NOT EXISTS idx_mensajes_usuario ON mensajes (user_id, id);

-- Perfiles de jugador (v5). El id de Telegram identifica al perfil.
CREATE TABLE IF NOT EXISTS perfiles (
    user_id        INTEGER PRIMARY KEY,             -- id de Telegram: un perfil por usuario
    genero         TEXT    NOT NULL,                -- género de videojuego (RPG, acción, ...)
    juego_favorito TEXT    NOT NULL,
    plataforma     TEXT    NOT NULL,
    precio_maximo  INTEGER NOT NULL,                -- en pesos; 0 = sin límite
    fecha          TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


async def inicializar() -> None:
    """Crea las tablas y el índice si todavía no existen."""
    # "async with" abre la conexión y garantiza que se cierre al terminar el
    # bloque, incluso si ocurre un error.
    async with aiosqlite.connect(RUTA_DB) as db:
        # Si quedó la tabla de la primera versión de la v5 (con teléfono), se
        # descarta: el esquema nuevo usa el id de Telegram como clave.
        cursor = await db.execute("PRAGMA table_info(perfiles)")
        columnas = [fila[1] for fila in await cursor.fetchall()]
        if "telefono" in columnas:
            logger.warning("Se descarta la tabla perfiles anterior, que usaba teléfono.")
            await db.execute("DROP TABLE perfiles")

        await db.executescript(ESQUEMA)  # executescript ejecuta varias sentencias SQL
        await db.commit()                # confirma los cambios en el archivo


async def guardar_intercambio(user_id: int, pregunta: str, respuesta: str) -> None:
    """Guarda en una sola operación el mensaje del usuario y la respuesta del modelo."""
    async with aiosqlite.connect(RUTA_DB) as db:
        # executemany ejecuta la misma sentencia con cada tupla de la lista.
        # Los signos ? son parámetros: SQLite inserta los valores de forma
        # segura, lo que evita la inyección de SQL.
        await db.executemany(
            "INSERT INTO mensajes (user_id, rol, texto) VALUES (?, ?, ?)",
            [(user_id, "user", pregunta),       # primera fila: la pregunta
             (user_id, "model", respuesta)],    # segunda fila: la respuesta
        )
        await db.commit()


async def obtener_historial(user_id: int, limite: int) -> list[tuple[str, str]]:
    """Devuelve los últimos `limite` mensajes del usuario, del más antiguo al más reciente."""
    async with aiosqlite.connect(RUTA_DB) as db:
        # ORDER BY id DESC: del más reciente al más antiguo.
        # LIMIT ?: solo los últimos `limite` mensajes.
        cursor = await db.execute(
            "SELECT rol, texto FROM mensajes WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, limite),
        )
        # fetchall devuelve una lista de tuplas (rol, texto).
        filas = await cursor.fetchall()

    # La consulta trajo los mensajes del más reciente al más antiguo.
    # reversed los invierte para que el modelo lea la conversación en orden
    # cronológico, y list convierte el resultado en una lista.
    return list(reversed(filas))


async def borrar_historial(user_id: int) -> int:
    """Borra la conversación de un usuario y devuelve cuántos mensajes eliminó."""
    async with aiosqlite.connect(RUTA_DB) as db:
        cursor = await db.execute("DELETE FROM mensajes WHERE user_id = ?", (user_id,))
        await db.commit()
        # rowcount indica cuántas filas afectó la última sentencia.
        return cursor.rowcount


async def guardar_perfil(user_id: int, perfil) -> None:
    """Guarda o actualiza el perfil de un usuario (un objeto PerfilUsuario)."""
    async with aiosqlite.connect(RUTA_DB) as db:
        # ON CONFLICT actualiza la fila si el usuario ya tenía un perfil.
        await db.execute(
            "INSERT INTO perfiles "
            "(user_id, genero, juego_favorito, plataforma, precio_maximo) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "genero = excluded.genero, "
            "juego_favorito = excluded.juego_favorito, "
            "plataforma = excluded.plataforma, "
            "precio_maximo = excluded.precio_maximo, "
            "fecha = CURRENT_TIMESTAMP",
            (
                user_id,
                perfil.genero,
                perfil.juego_favorito,
                perfil.plataforma,
                perfil.precio_maximo,
            ),
        )
        await db.commit()


async def obtener_perfil(user_id: int) -> dict | None:
    """Devuelve el perfil del usuario como diccionario, o None si no existe."""
    async with aiosqlite.connect(RUTA_DB) as db:
        cursor = await db.execute(
            "SELECT genero, juego_favorito, plataforma, precio_maximo "
            "FROM perfiles WHERE user_id = ?",
            (user_id,),
        )
        fila = await cursor.fetchone()

    if fila is None:
        return None
    return {
        "genero": fila[0],
        "juego_favorito": fila[1],
        "plataforma": fila[2],
        "precio_maximo": fila[3],
    }
