from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import os

from cache import init_db
from api_football import buscar_estatisticas_time, buscar_times_por_nome
from probabilidades import calcular_analise_completa

load_dotenv()

API_KEY = os.getenv("API_FOOTBALL_KEY")
if not API_KEY:
    raise RuntimeError("API_FOOTBALL_KEY não definida no .env")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Analisador de Apostas de Futebol", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/teams/search")
async def buscar_times(nome: str = Query(..., min_length=3)):
    """Busca times por nome para o autocomplete."""
    times = await buscar_times_por_nome(nome, API_KEY)
    return {"times": times}


@app.get("/analyze")
async def analisar_partida(
    home_team_id: int,
    away_team_id: int,
    league_id: int = 71,
    season: int = 2024,
):
    """
    Retorna análise probabilística completa para uma partida.
    Usa cache SQLite para economizar requisições da API.
    """
    stats_casa = await buscar_estatisticas_time(home_team_id, league_id, season, API_KEY)
    stats_fora = await buscar_estatisticas_time(away_team_id, league_id, season, API_KEY)

    if not stats_casa or not stats_fora:
        raise HTTPException(status_code=404, detail="Estatísticas não encontradas para um ou ambos os times.")

    analise = calcular_analise_completa(stats_casa, stats_fora)
    return {
        "time_casa": stats_casa["info"],
        "time_fora": stats_fora["info"],
        "estatisticas_casa": stats_casa["stats"],
        "estatisticas_fora": stats_fora["stats"],
        "probabilidades": analise,
    }
