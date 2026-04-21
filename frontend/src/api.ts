import axios from "axios";
import type { Time, AnaliseResponse } from "./types";

const api = axios.create({ baseURL: "http://localhost:8000" });

export async function buscarTimes(nome: string): Promise<Time[]> {
  const { data } = await api.get("/teams/search", { params: { nome } });
  return data.times;
}

export async function analisarPartida(
  homeId: number,
  awayId: number,
  leagueId: number,
  season: number
): Promise<AnaliseResponse> {
  const { data } = await api.get("/analyze", {
    params: {
      home_team_id: homeId,
      away_team_id: awayId,
      league_id: leagueId,
      season,
    },
  });
  return data;
}
