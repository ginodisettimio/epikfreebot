"""
Memoria: historial de conversación en SQLite.

Cada mensaje (del usuario o del modelo) se guarda como una fila de la tabla
`mensajes`. Se utiliza aiosqlite, la versión asíncrona de sqlite3, para que
las operaciones sobre la base no bloqueen al bot mientras atiende a otros
usuarios.
"""

import aiosqlite                        # SQLite con soporte para async/await

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
"""


async def inicializar() -> None:
    """Crea la tabla y el índice si todavía no existen."""
    # "async with" abre la conexión y garantiza que se cierre al terminar el
    # bloque, incluso si ocurre un error.
    async with aiosqlite.connect(RUTA_DB) as db:
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
        