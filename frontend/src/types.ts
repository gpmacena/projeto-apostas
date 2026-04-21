export interface Time {
  id: number;
  nome: string;
  logo: string;
  pais: string;
}

export interface StatsTime {
  jogos: number;
  gols_marcados_media_casa: number;
  gols_marcados_media_fora: number;
  gols_sofridos_media_casa: number;
  gols_sofridos_media_fora: number;
  escanteios_marcados_media: number;
  escanteios_sofridos_media: number;
}

export interface Probabilidades {
  lambda_casa: number;
  lambda_fora: number;
  resultado: {
    vitoria_casa: number;
    empate: number;
    vitoria_fora: number;
  };
  over_under_gols: {
    over_1_5: number;
    over_2_5: number;
    over_3_5: number;
    btts: number;
  };
  placares_top: { placar: string; prob: number }[];
  escanteios: {
    media_total: number;
    over_7_5: number;
    over_8_5: number;
    over_9_5: number;
    over_10_5: number;
    over_11_5: number;
  };
}

export interface AnaliseResponse {
  time_casa: { id: number; nome: string; logo: string };
  time_fora: { id: number; nome: string; logo: string };
  estatisticas_casa: StatsTime;
  estatisticas_fora: StatsTime;
  probabilidades: Probabilidades;
}
