import httpx
from cache import get_cache, set_cache

BASE_URL = "https://v3.football.api-sports.io"


def _headers(api_key: str) -> dict:
    return {"x-apisports-key": api_key}


async def buscar_times_por_nome(nome: str, api_key: str) -> list[dict]:
    chave = f"times_busca:{nome.lower()}"
    cached = await get_cache(chave)
    if cached:
        return cached

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/teams",
            headers=_headers(api_key),
            params={"search": nome},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

    times = [
        {
            "id": t["team"]["id"],
            "nome": t["team"]["name"],
            "logo": t["team"]["logo"],
            "pais": t["team"]["country"],
        }
        for t in data.get("response", [])
    ]
    await set_cache(chave, times)
    return times


async def buscar_estatisticas_time(team_id: int, league_id: int, season: int, api_key: str) -> dict | None:
    chave = f"stats:{team_id}:{league_id}:{season}"
    cached = await get_cache(chave)
    if cached:
        return cached

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/teams/statistics",
            headers=_headers(api_key),
            params={"team": team_id, "league": league_id, "season": season},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

    r = data.get("response")
    if not r:
        return None

    team_info = r["team"]
    fixtures = r["fixtures"]
    goals = r["goals"]
    corners = r.get("corners") or {}

    jogos_casa = fixtures["played"]["home"] or 1
    jogos_fora = fixtures["played"]["away"] or 1
    jogos_total = fixtures["played"]["total"] or 1

    # médias de gols marcados e sofridos
    gols_marcados_casa = (goals["for"]["total"]["home"] or 0) / jogos_casa
    gols_marcados_fora = (goals["for"]["total"]["away"] or 0) / jogos_fora
    gols_sofridos_casa = (goals["against"]["total"]["home"] or 0) / jogos_casa
    gols_sofridos_fora = (goals["against"]["total"]["away"] or 0) / jogos_fora

    # escanteios — a API retorna por posição (home/away), média por jogo
    cant_marcados = _media_corners(corners.get("for", {}), jogos_total)
    cant_sofridos = _media_corners(corners.get("against", {}), jogos_total)

    resultado = {
        "info": {
            "id": team_info["id"],
            "nome": team_info["name"],
            "logo": team_info["logo"],
        },
        "stats": {
            "jogos": jogos_total,
            "gols_marcados_media_casa": round(gols_marcados_casa, 2),
            "gols_marcados_media_fora": round(gols_marcados_fora, 2),
            "gols_sofridos_media_casa": round(gols_sofridos_casa, 2),
            "gols_sofridos_media_fora": round(gols_sofridos_fora, 2),
            "escanteios_marcados_media": round(cant_marcados, 2),
            "escanteios_sofridos_media": round(cant_sofridos, 2),
        },
    }

    await set_cache(chave, resultado)
    return resultado


def _media_corners(corners_obj: dict, jogos: int) -> float:
    """Soma total de escanteios e divide pelo número de jogos."""
    total = (corners_obj.get("total") or {})
    if isinstance(total, dict):
        soma = sum(v for v in total.values() if isinstance(v, (int, float)))
    else:
        soma = total or 0
    return soma / jogos if jogos else 0
