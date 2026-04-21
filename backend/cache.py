import aiosqlite
import json
import time

DB_PATH = "cache.db"
TTL_SECONDS = 60 * 60 * 6  # 6 horas


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                chave TEXT PRIMARY KEY,
                valor TEXT NOT NULL,
                criado_em INTEGER NOT NULL
            )
        """)
        await db.commit()


async def get_cache(chave: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT valor, criado_em FROM cache WHERE chave = ?", (chave,)) as cursor:
            row = await cursor.fetchone()
            if row and (time.time() - row[1]) < TTL_SECONDS:
                return json.loads(row[0])
    return None


async def set_cache(chave: str, valor: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO cache (chave, valor, criado_em) VALUES (?, ?, ?)",
            (chave, json.dumps(valor), int(time.time())),
        )
        await db.commit()
