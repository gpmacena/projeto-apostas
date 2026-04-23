#!/usr/bin/env python3
"""
Busca jogos dos próximos 3 dias, calcula probabilidades Poisson e gera
index.html estático com apostas recomendadas + análise completa.
"""

import os, sys, json, time, itertools, math
import requests
import numpy as np
from scipy.stats import poisson


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer): return int(obj)
        if isinstance(obj, np.floating): return float(obj)
        if isinstance(obj, np.bool_):   return bool(obj)
        return super().default(obj)
from datetime import datetime, timezone, timedelta
from pathlib import Path

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
if not API_KEY:
    sys.exit("ERRO: API_FOOTBALL_KEY não definida")

BASE_URL = "https://v3.football.api-sports.io"
HEADERS  = {"x-apisports-key": API_KEY}

BRT   = timezone(timedelta(hours=-3))
_now  = datetime.now(BRT)
AGORA = _now.strftime("%d/%m/%Y %H:%M")
ANO   = _now.year
MES   = _now.month

# Datas que serão buscadas
DATAS = [(_now + timedelta(days=d)).strftime("%Y-%m-%d") for d in range(2)]
HOJE  = DATAS[0]

LIGAS = {
    71:  "🇧🇷 Brasileirão Série A",
    72:  "🇧🇷 Brasileirão Série B",
    2:   "🌍 Champions League",
    3:   "🌍 Europa League",
    39:  "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League",
    140: "🇪🇸 La Liga",
    135: "🇮🇹 Serie A",
    78:  "🇩🇪 Bundesliga",
    61:  "🇫🇷 Ligue 1",
}

FATOR_CASA = 1.1
MAX_GOLS   = 7
ULTIMOS_N  = 6

# Limiares de confiança para sugerir aposta
LIMIAR_FORTE  = 68.0
LIMIAR_MEDIO  = 55.0   # coleta a partir de 55% — a filtragem por odd é feita no HTML
ODD_MINIMA    = 1.50   # só mostra apostas onde a odd justa >= 1.50 (prob <= 66.7%)

_cache_stats   = {}
_cache_corners = {}


# ── API helpers ───────────────────────────────────────────────────────────────

def _temporada(liga_id: int) -> int:
    return ANO if liga_id in {71, 72, 73, 75} else (ANO - 1 if MES < 7 else ANO)


def _get(endpoint: str, params: dict):
    time.sleep(0.25)
    r = requests.get(f"{BASE_URL}/{endpoint}", headers=HEADERS, params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("response", [])


def buscar_jogos(liga_id: int, data: str) -> list:
    return _get("fixtures", {"league": liga_id, "date": data, "season": _temporada(liga_id)})


def buscar_stats(team_id: int, liga_id: int) -> dict | None:
    k = (team_id, liga_id)
    if k not in _cache_stats:
        data = _get("teams/statistics", {"team": team_id, "league": liga_id, "season": _temporada(liga_id)})
        _cache_stats[k] = data if data else None
    return _cache_stats[k]


def buscar_media_escanteios(team_id: int, liga_id: int) -> float:
    k = (team_id, liga_id)
    if k in _cache_corners:
        return _cache_corners[k]
    fixtures = _get("fixtures", {"team": team_id, "league": liga_id,
                                  "season": _temporada(liga_id), "status": "FT", "last": ULTIMOS_N})
    total, n = 0, 0
    for f in fixtures:
        stats = _get("fixtures/statistics", {"fixture": f["fixture"]["id"], "team": team_id})
        if stats:
            for s in stats[0].get("statistics", []):
                if s["type"] == "Corner Kicks" and s["value"] is not None:
                    total += int(s["value"]); n += 1; break
    media = (total / n) if n else 4.5
    _cache_corners[k] = media
    return media


# ── Cálculos ──────────────────────────────────────────────────────────────────

def extrair_medias(stats: dict, team_id: int, liga_id: int) -> dict:
    f  = stats.get("fixtures", {})
    g  = stats.get("goals", {})
    cs = stats.get("clean_sheet", {})
    fs = stats.get("failed_to_score", {})

    jc = f.get("played", {}).get("home")  or 1
    jf = f.get("played", {}).get("away")  or 1
    jt = f.get("played", {}).get("total") or 1

    gmc = (g.get("for",     {}).get("total", {}).get("home") or 0) / jc
    gmf = (g.get("for",     {}).get("total", {}).get("away") or 0) / jf
    gsc = (g.get("against", {}).get("total", {}).get("home") or 0) / jc
    gsf = (g.get("against", {}).get("total", {}).get("away") or 0) / jf
    escanteios = buscar_media_escanteios(team_id, liga_id)

    return {
        # usados no Poisson
        "gols_marc_casa": gmc,
        "gols_marc_fora": gmf,
        "gols_sofr_casa": gsc,
        "gols_sofr_fora": gsf,
        "escanteios":     escanteios,
        # dados extras para aba Verificar
        "jogos_total":  jt,
        "jogos_casa":   jc,
        "jogos_fora":   jf,
        "gols_marcados_total": g.get("for",     {}).get("total", {}).get("total") or 0,
        "gols_sofridos_total": g.get("against", {}).get("total", {}).get("total") or 0,
        "media_gols_marc": round((gmc + gmf) / 2, 2),
        "media_gols_sofr": round((gsc + gsf) / 2, 2),
        "clean_sheets":  (cs.get("total") or 0),
        "sem_marcar":    (fs.get("total") or 0),
        "forma": (stats.get("form") or "")[-5:],
    }


def calcular_probs(mc: dict, mf: dict) -> dict:
    lam_c = max(mc["gols_marc_casa"] * mf["gols_sofr_fora"] * FATOR_CASA, 0.3)
    lam_f = max(mf["gols_marc_fora"] * mc["gols_sofr_casa"], 0.3)

    mat = np.zeros((MAX_GOLS, MAX_GOLS))
    for i in range(MAX_GOLS):
        for j in range(MAX_GOLS):
            mat[i][j] = poisson.pmf(i, lam_c) * poisson.pmf(j, lam_f)

    vc  = float(np.sum(np.tril(mat, -1)))
    emp = float(np.sum(np.diag(mat)))
    vf  = float(np.sum(np.triu(mat, 1)))
    tot = vc + emp + vf

    med_cant = mc["escanteios"] + mf["escanteios"]

    placares = sorted(
        [{"p": f"{i}x{j}", "v": round(mat[i][j] * 100, 1)} for i in range(MAX_GOLS) for j in range(MAX_GOLS)],
        key=lambda x: x["v"], reverse=True,
    )[:6]

    return {
        "lam_c": round(lam_c, 2), "lam_f": round(lam_f, 2),
        "vc":    round(vc  / tot * 100, 1),
        "emp":   round(emp / tot * 100, 1),
        "vf":    round(vf  / tot * 100, 1),
        "dc1x":  round((vc + emp) / tot * 100, 1),
        "dcx2":  round((emp + vf) / tot * 100, 1),
        "o15":   round((1 - float(np.sum(mat[:2, :2]))) * 100, 1),
        "o25":   round((1 - float(np.sum(mat[:3, :3]))) * 100, 1),
        "o35":   round((1 - float(np.sum(mat[:4, :4]))) * 100, 1),
        "u25":   round(float(np.sum(mat[:3, :3])) * 100, 1),
        "btts":  round(float(np.sum(mat[1:, 1:])) * 100, 1),
        "no_btts": round(float(1 - np.sum(mat[1:, 1:])) * 100, 1),
        "cant_media": round(med_cant, 1),
        "o85":   round((1 - poisson.cdf(8,  med_cant)) * 100, 1),
        "o95":   round((1 - poisson.cdf(9,  med_cant)) * 100, 1),
        "o105":  round((1 - poisson.cdf(10, med_cant)) * 100, 1),
        "u95":   round(poisson.cdf(9, med_cant) * 100, 1),
        "placares": placares,
    }


def extrair_apostas(jogo: dict) -> list:
    """Retorna lista de apostas sugeridas para o jogo, ordenada por probabilidade."""
    p = jogo.get("probs")
    if not p:
        return []

    home = jogo["home"]["nome"]
    away = jogo["away"]["nome"]

    candidatas = [
        {"mercado": f"Vitória {home}",    "prob": p["vc"],       "cod": "1"},
        {"mercado": f"Vitória {away}",    "prob": p["vf"],       "cod": "2"},
        {"mercado": f"Dupla Chance: {home} ou Empate", "prob": p["dc1x"], "cod": "1X"},
        {"mercado": f"Dupla Chance: Empate ou {away}", "prob": p["dcx2"], "cod": "X2"},
        {"mercado": "Over 1.5 gols",      "prob": p["o15"],      "cod": "O1.5"},
        {"mercado": "Over 2.5 gols",      "prob": p["o25"],      "cod": "O2.5"},
        {"mercado": "Over 3.5 gols",      "prob": p["o35"],      "cod": "O3.5"},
        {"mercado": "Under 2.5 gols",     "prob": p["u25"],      "cod": "U2.5"},
        {"mercado": "BTTS — Ambos marcam","prob": p["btts"],     "cod": "BTTS"},
        {"mercado": "BTTS — Não",         "prob": p["no_btts"],  "cod": "BTTS-N"},
        {"mercado": "Over 8.5 escanteios","prob": p["o85"],      "cod": "O8.5C"},
        {"mercado": "Over 9.5 escanteios","prob": p["o95"],      "cod": "O9.5C"},
        {"mercado": "Over 10.5 escanteios","prob": p["o105"],    "cod": "O10.5C"},
        {"mercado": "Under 9.5 escanteios","prob": p["u95"],     "cod": "U9.5C"},
    ]

    sugeridas = [c for c in candidatas if c["prob"] >= LIMIAR_MEDIO]
    sugeridas.sort(key=lambda x: x["prob"], reverse=True)

    for s in sugeridas:
        s["forte"] = s["prob"] >= LIMIAR_FORTE
        s["home"]  = home
        s["away"]  = away
        s["horario"] = jogo["horario"]
        s["data"]    = jogo["data"]
        s["home_logo"] = jogo["home"]["logo"]
        s["away_logo"] = jogo["away"]["logo"]

    return sugeridas


# ── Processamento ─────────────────────────────────────────────────────────────

def processar_liga(liga_id: int) -> list:
    nome = LIGAS[liga_id]
    print(f"  {nome}...")
    jogos = []

    for data in DATAS:
        try:
            fixtures = buscar_jogos(liga_id, data)
        except Exception as e:
            print(f"    ERRO fixtures {data}: {e}", file=sys.stderr)
            continue

        for f in fixtures:
            home   = f["teams"]["home"]
            away   = f["teams"]["away"]
            status = f["fixture"]["status"]["short"]

            try:
                dt_utc  = datetime.fromisoformat(f["fixture"]["date"].replace("Z", "+00:00"))
                horario = dt_utc.astimezone(BRT).strftime("%H:%M")
            except Exception:
                horario = "--:--"

            label_data = "Hoje" if data == HOJE else \
                         "Amanhã" if data == DATAS[1] else \
                         datetime.strptime(data, "%Y-%m-%d").strftime("%d/%m")

            print(f"    [{label_data}] {home['name']} x {away['name']} ({horario})")

            probs, mc, mf = None, None, None
            try:
                sh = buscar_stats(home["id"], liga_id)
                sa = buscar_stats(away["id"], liga_id)
                if sh and sa:
                    mc    = extrair_medias(sh, home["id"], liga_id)
                    mf    = extrair_medias(sa, away["id"], liga_id)
                    probs = calcular_probs(mc, mf)
            except Exception as e:
                print(f"      ERRO probs: {e}", file=sys.stderr)

            verificar = None
            if mc and mf and probs:
                verificar = {
                    "home_stats": {
                        "jogos_total":  mc["jogos_total"],
                        "jogos_casa":   mc["jogos_casa"],
                        "media_gols_marc": round(mc["gols_marc_casa"], 2),
                        "media_gols_sofr": round(mc["gols_sofr_casa"], 2),
                        "escanteios":   round(mc["escanteios"], 1),
                        "clean_sheets": mc["clean_sheets"],
                        "sem_marcar":   mc["sem_marcar"],
                        "forma":        mc["forma"],
                    },
                    "away_stats": {
                        "jogos_total":  mf["jogos_total"],
                        "jogos_fora":   mf["jogos_fora"],
                        "media_gols_marc": round(mf["gols_marc_fora"], 2),
                        "media_gols_sofr": round(mf["gols_sofr_fora"], 2),
                        "escanteios":   round(mf["escanteios"], 1),
                        "clean_sheets": mf["clean_sheets"],
                        "sem_marcar":   mf["sem_marcar"],
                        "forma":        mf["forma"],
                    },
                    "poisson": {
                        "lam_c": probs["lam_c"],
                        "lam_f": probs["lam_f"],
                        "calc_c": f"{round(mc['gols_marc_casa'],2)} × {round(mf['gols_sofr_fora'],2)} × {FATOR_CASA}",
                        "calc_f": f"{round(mf['gols_marc_fora'],2)} × {round(mc['gols_sofr_casa'],2)}",
                    },
                }

            jogos.append({
                "data":    label_data,
                "data_iso": data,
                "horario": horario,
                "status":  status,
                "home": {"id": home["id"], "nome": home["name"], "logo": home["logo"]},
                "away": {"id": away["id"], "nome": away["name"], "logo": away["logo"]},
                "probs":    probs,
                "verificar": verificar,
            })

    return jogos


def _to_sel(a: dict) -> dict:
    return {
        "mercado":   a["mercado"],
        "home":      a["home"],
        "away":      a["away"],
        "home_logo": a["home_logo"],
        "away_logo": a["away_logo"],
        "prob":      a["prob"],
        "odd":       round(a["odd_impl"], 2),
        "data":      a["data"],
        "horario":   a["horario"],
        "liga":      a["liga"],
    }


def _gerar_multiplas_para(apostas: list) -> list:
    """Gera múltiplas (odd 1.50-2.05) para uma lista de apostas de um mesmo dia."""
    candidatas = [
        {**a, "odd_impl": round(100 / a["prob"], 3)}
        for a in apostas if 65 <= a["prob"] <= 88
    ]
    if len(candidatas) < 2:
        return []

    candidatas.sort(key=lambda x: x["odd_impl"], reverse=True)
    candidatas = candidatas[:25]

    multiplas = []
    for r in range(2, 5):
        for combo in itertools.combinations(candidatas, r):
            partidas = [(a["home"], a["away"]) for a in combo]
            if len(set(partidas)) != len(partidas):
                continue
            odd_total = round(math.prod(a["odd_impl"] for a in combo), 2)
            if not (1.50 <= odd_total <= 2.05):
                continue
            prob_total = round(math.prod(a["prob"] / 100 for a in combo) * 100, 1)
            multiplas.append({
                "n":          r,
                "odd_total":  odd_total,
                "prob_total": prob_total,
                "selecoes":   [_to_sel(a) for a in combo],
            })

    multiplas.sort(key=lambda x: (-x["prob_total"], x["odd_total"]))

    vistos: set = set()
    resultado = []
    for m in multiplas:
        chave = frozenset((s["home"], s["away"]) for s in m["selecoes"])
        if chave not in vistos:
            vistos.add(chave)
            resultado.append(m)
        if len(resultado) >= 12:
            break
    return resultado


def gerar_multiplas(apostas_por_liga: dict) -> dict:
    """
    Retorna dict {label_data: [multiplas]} agrupado por dia.
    Prioriza jogos do mesmo dia; datas sem bets suficientes são omitidas.
    """
    # Flatten com liga e odd_impl
    todas = []
    for liga, apostas in apostas_por_liga.items():
        for a in apostas:
            todas.append({**a, "liga": liga})

    # Agrupa por label de data preservando ordem (Hoje → Amanhã → datas extras)
    por_data: dict = {}
    for a in todas:
        por_data.setdefault(a["data"], []).append(a)

    resultado: dict = {}
    for data_label, apostas_dia in por_data.items():
        mults = _gerar_multiplas_para(apostas_dia)
        if mults:
            resultado[data_label] = mults

    return resultado


def gerar_dados() -> dict:
    ligas: dict = {}
    apostas_por_liga: dict = {}
    total_jogos = 0

    for liga_id, nome in LIGAS.items():
        jogos = processar_liga(liga_id)
        if not jogos:
            continue

        ligas[nome] = jogos
        total_jogos += len(jogos)

        # Extrai apostas de todos os jogos da liga
        todas_apostas = []
        for j in jogos:
            todas_apostas.extend(extrair_apostas(j))

        todas_apostas.sort(key=lambda x: x["prob"], reverse=True)
        apostas_por_liga[nome] = todas_apostas[:20]

    return {
        "data":             AGORA,
        "hoje":             HOJE,
        "datas":            DATAS,
        "total_jogos":      total_jogos,
        "ligas":            ligas,
        "apostas_por_liga": apostas_por_liga,
        "odd_minima":       ODD_MINIMA,
        "multiplas":        gerar_multiplas(apostas_por_liga),
    }


# ── HTML ──────────────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>⚽ Apostas Futebol</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#0f172a;color:#f1f5f9;font-family:'Inter',system-ui,sans-serif;min-height:100vh;padding-bottom:60px}
header{background:#1e293b;border-bottom:2px solid #3b82f6;padding:16px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;position:sticky;top:0;z-index:50}
.logo{font-size:20px;font-weight:800;letter-spacing:-.5px}
.badge{background:#0f172a;border:1px solid #334155;border-radius:20px;padding:4px 14px;font-size:12px;color:#64748b}

/* Tabs */
.tabs{display:flex;gap:0;border-bottom:1px solid #334155;background:#1e293b;position:sticky;top:61px;z-index:40}
.tab{padding:12px 20px;font-size:13px;font-weight:600;cursor:pointer;color:#64748b;border-bottom:3px solid transparent;transition:all .2s;background:none;border-top:none;border-left:none;border-right:none}
.tab:hover{color:#f1f5f9}
.tab.ativo{color:#38bdf8;border-bottom-color:#38bdf8}

main{max-width:920px;margin:0 auto;padding:20px 16px;display:flex;flex-direction:column;gap:24px}

/* Seção de apostas */
.liga-bloco{display:flex;flex-direction:column;gap:10px}
.liga-header{font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#94a3b8;padding-bottom:10px;border-bottom:1px solid #1e293b;display:flex;align-items:center;justify-content:space-between}
.conta-badge{background:#3b82f620;color:#38bdf8;border-radius:12px;padding:2px 10px;font-size:11px}

/* Card de aposta */
.aposta{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:12px 14px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.aposta.forte{border-left:3px solid #34d399}
.aposta.medio{border-left:3px solid #fbbf24}
.logos{display:flex;align-items:center;gap:4px;flex-shrink:0}
.logos img{width:22px;height:22px;object-fit:contain}
.aposta-info{flex:1;min-width:140px}
.aposta-partida{font-size:11px;color:#64748b;margin-bottom:2px}
.aposta-mercado{font-size:14px;font-weight:700;color:#f1f5f9}
.aposta-meta{display:flex;align-items:center;gap:12px;margin-left:auto}
.aposta-data{font-size:11px;color:#475569;white-space:nowrap}
.prob-badge{padding:5px 12px;border-radius:8px;font-size:15px;font-weight:800;min-width:58px;text-align:center}
.prob-forte{background:#052e16;color:#34d399}
.prob-medio{background:#1c1a05;color:#fbbf24}
.odd-impl{font-size:11px;color:#475569;text-align:center;margin-top:2px}

/* Jogos (análise) */
.card{background:#1e293b;border:1px solid #334155;border-radius:12px;overflow:hidden}
.card-topo{display:flex;align-items:center;justify-content:space-between;padding:14px 16px 10px;gap:12px;flex-wrap:wrap}
.times{display:flex;align-items:center;gap:16px;flex:1;min-width:180px}
.time-bloco{display:flex;flex-direction:column;align-items:center;gap:5px;flex:1;text-align:center}
.time-bloco img{width:36px;height:36px;object-fit:contain}
.time-nome{font-size:13px;font-weight:600;line-height:1.2}
.vs{font-size:17px;font-weight:800;color:#475569;flex-shrink:0}
.card-meta{display:flex;flex-direction:column;align-items:flex-end;gap:3px}
.horario{font-size:13px;color:#64748b;white-space:nowrap}
.data-tag{font-size:11px;color:#3b82f6;font-weight:600}
.status-live{color:#ef4444;font-weight:700;font-size:12px;animation:blink 1.2s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.4}}
.probs{padding:0 16px 14px;display:flex;flex-direction:column;gap:10px}
.resultado{display:flex;gap:8px}
.res-item{flex:1;background:#0f172a;border-radius:8px;padding:8px 6px;text-align:center}
.res-label{font-size:11px;color:#64748b;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.res-valor{font-size:18px;font-weight:700}
.res-bar{height:4px;border-radius:2px;margin-top:6px;background:#1e293b}
.res-fill{height:100%;border-radius:2px}
.ou-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
.ou-item{background:#0f172a;border-radius:6px;padding:7px 8px;display:flex;justify-content:space-between;align-items:center}
.ou-label{font-size:11px;color:#94a3b8}
.ou-val{font-size:13px;font-weight:700}
.cant-row{display:flex;justify-content:space-between;font-size:11px;color:#475569;padding:0 2px}
.placares-row{display:flex;gap:6px;flex-wrap:wrap}
.plac{background:#0f172a;border-radius:6px;padding:5px 10px;display:flex;flex-direction:column;align-items:center;gap:2px}
.plac-score{font-size:13px;font-weight:700;color:#f1f5f9}
.plac-pct{font-size:11px;color:#64748b}
.sem-probs{font-size:12px;color:#475569;padding:0 16px 14px;font-style:italic}
.vazio{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:40px;text-align:center;color:#475569;font-size:15px}

/* Filtro de data */
.filtros{display:flex;gap:8px;flex-wrap:wrap}
.filtro-btn{padding:6px 14px;border-radius:20px;border:1px solid #334155;background:none;color:#64748b;font-size:12px;font-weight:600;cursor:pointer;transition:all .2s}
.filtro-btn.ativo{background:#3b82f620;border-color:#3b82f6;color:#38bdf8}

.verde{color:#34d399}.amarelo{color:#fbbf24}.vermelho{color:#f87171}.azul{color:#38bdf8}

/* Múltiplas */
.mult-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}
.mult-card{background:#1e293b;border:1px solid #334155;border-radius:12px;overflow:hidden}
.mult-header{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:#0f172a;border-bottom:1px solid #334155}
.mult-n{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#64748b}
.mult-odds{display:flex;align-items:center;gap:12px}
.mult-odd-total{font-size:22px;font-weight:800;color:#f1f5f9}
.mult-prob-total{font-size:12px;color:#64748b;text-align:right}
.mult-selecoes{display:flex;flex-direction:column;gap:0}
.mult-sel{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid #0f172a}
.mult-sel:last-child{border-bottom:none}
.mult-sel-logos{display:flex;gap:3px;flex-shrink:0}
.mult-sel-logos img{width:20px;height:20px;object-fit:contain}
.mult-sel-info{flex:1;min-width:0}
.mult-sel-partida{font-size:11px;color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mult-sel-mercado{font-size:13px;font-weight:600;color:#f1f5f9}
.mult-sel-odd{text-align:right;flex-shrink:0}
.mult-sel-odd-val{font-size:14px;font-weight:700;color:#38bdf8}
.mult-sel-prob{font-size:11px;color:#64748b}
.mult-footer{padding:10px 14px;background:#0f172a;display:flex;align-items:center;justify-content:space-between;font-size:12px;border-top:1px solid #334155}
.retorno{color:#34d399;font-weight:700}

/* Verificar */
.ver-card{background:#1e293b;border:1px solid #334155;border-radius:12px;overflow:hidden;margin-bottom:12px}
.ver-header{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #334155;flex-wrap:wrap;gap:8px}
.ver-match{display:flex;align-items:center;gap:10px;font-weight:700;font-size:14px}
.ver-match img{width:26px;height:26px;object-fit:contain}
.ver-body{display:grid;grid-template-columns:1fr 1fr;gap:0}
.ver-col{padding:14px 16px}
.ver-col:first-child{border-right:1px solid #334155}
.ver-col-titulo{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#64748b;margin-bottom:10px;display:flex;align-items:center;gap:6px}
.ver-col-titulo img{width:20px;height:20px;object-fit:contain}
.ver-row{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid #0f172a;font-size:13px}
.ver-row:last-child{border-bottom:none}
.ver-lbl{color:#64748b}
.ver-val{font-weight:600;color:#f1f5f9}
.forma-pills{display:flex;gap:4px;flex-wrap:wrap;margin:8px 0}
.pill{width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:800}
.pill-W{background:#052e16;color:#34d399}
.pill-D{background:#1c1a05;color:#fbbf24}
.pill-L{background:#450a0a;color:#f87171}
.ver-poisson{background:#0f172a;padding:12px 16px;border-top:1px solid #334155;font-size:12px;color:#94a3b8;display:flex;flex-direction:column;gap:4px}
.ver-poisson strong{color:#38bdf8}
.ver-poisson code{background:#1e293b;padding:2px 6px;border-radius:4px;font-family:monospace;color:#f1f5f9}

@media(max-width:500px){.ou-grid{grid-template-columns:repeat(2,1fr)}.tab{padding:10px 14px;font-size:12px}.ver-body{grid-template-columns:1fr}.ver-col:first-child{border-right:none;border-bottom:1px solid #334155}}
</style>
</head>
<body>
<script>window.DATA=__DATA__;</script>

<header>
  <div>
    <div class="logo">⚽ Futebol · Apostas & Análise</div>
    <div style="font-size:12px;color:#64748b;margin-top:3px">Poisson · Próximos 3 dias</div>
  </div>
  <div class="badge" id="badge-data"></div>
</header>

<div class="tabs">
  <button class="tab ativo" onclick="mudarTab('apostas',this)">🎯 Apostas</button>
  <button class="tab" onclick="mudarTab('multiplas',this)">🎰 Múltiplas</button>
  <button class="tab" onclick="mudarTab('analise',this)">📊 Análise</button>
  <button class="tab" onclick="mudarTab('verificar',this)">🔍 Verificar</button>
</div>

<main id="app"></main>

<script>
const D = window.DATA;
document.getElementById('badge-data').textContent = '📅 ' + D.hoje + ' · ' + D.data;

let tabAtual = 'apostas';
let filtroData = 'Todos';
let filtroMultiplas = Object.keys(window.DATA.multiplas || {})[0] || 'Hoje';

function mudarTab(tab, el) {
  tabAtual = tab;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('ativo'));
  if (el) el.classList.add('ativo');
  render();
}

const cor  = v => v >= 68 ? 'verde' : v >= 60 ? 'amarelo' : 'vermelho';
const barC = {'verde':'#34d399','amarelo':'#fbbf24','vermelho':'#f87171'};
const oddImpl = p => (100 / p).toFixed(2);


// ── GLOSSÁRIO ─────────────────────────────────────────────────────────────────
const GLOSSARIO = [
  {cod:'1',    nome:'Vitória Casa',          desc:'O time mandante (da casa) vence no tempo normal.'},
  {cod:'2',    nome:'Vitória Fora',          desc:'O time visitante vence no tempo normal.'},
  {cod:'1X',   nome:'Dupla Chance: Casa ou Empate', desc:'Você ganha se o time da CASA vencer OU empatar. O nome do time da casa aparece na aposta. Cobre 2 dos 3 resultados — mais seguro que apostar só na vitória.'},
  {cod:'X2',   nome:'Dupla Chance: Empate ou Fora', desc:'Você ganha se o time VISITANTE vencer OU empatar. O nome do visitante aparece na aposta. Boa proteção quando o visitante é forte mas pode empatar.'},
  {cod:'O1.5', nome:'Over 1.5 gols',         desc:'O jogo termina com 2 ou mais gols no total. Muito frequente — odd costuma ser baixa.'},
  {cod:'O2.5', nome:'Over 2.5 gols',         desc:'3 ou mais gols no total. O mercado mais popular. Equilíbrio entre chance e odd.'},
  {cod:'O3.5', nome:'Over 3.5 gols',         desc:'4 ou mais gols no total. Menos provável, mas odd mais alta.'},
  {cod:'U2.5', nome:'Under 2.5 gols',        desc:'2 gols ou menos no total (0-0, 1-0, 1-1, 2-0, etc). Bom para jogos defensivos ou equilibrados.'},
  {cod:'BTTS', nome:'BTTS — Ambos marcam',   desc:'Os dois times marcam pelo menos 1 gol cada. Não importa o placar, só que ambos balançaram a rede.'},
  {cod:'BTTS-N',nome:'BTTS — Não',           desc:'Pelo menos um time NÃO marca. Inclui vitórias por 1-0, 2-0 e empate 0-0.'},
  {cod:'O8.5C',nome:'Over 8.5 escanteios',   desc:'9 ou mais escanteios no total dos dois times. Jogos com muita pressão ofensiva tendem a ter mais escanteios.'},
  {cod:'O9.5C',nome:'Over 9.5 escanteios',   desc:'10 ou mais escanteios. Mercado popular para acompanhar ao vivo.'},
  {cod:'O10.5C',nome:'Over 10.5 escanteios', desc:'11 ou mais escanteios. Odds mais atrativas, mas menos provável.'},
  {cod:'U9.5C',nome:'Under 9.5 escanteios',  desc:'9 ou menos escanteios. Jogos mais truncados ou de meio-campo tendem a ter menos escanteios.'},
];

let glossarioAberto = false;
function toggleGlossario() { glossarioAberto = !glossarioAberto; render(); }

function renderGlossario() {
  if (!glossarioAberto) return `
    <div onclick="toggleGlossario()" style="background:#1e293b;border:1px solid #334155;border-radius:10px;padding:12px 16px;cursor:pointer;display:flex;justify-content:space-between;align-items:center">
      <span style="font-size:13px;font-weight:600;color:#94a3b8">📖 O que significa cada tipo de aposta? <span style="color:#3b82f6">(clique para ver)</span></span>
      <span style="color:#64748b">▼</span>
    </div>`;
  return `
    <div style="background:#1e293b;border:1px solid #3b82f6;border-radius:10px;overflow:hidden">
      <div onclick="toggleGlossario()" style="padding:12px 16px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #334155">
        <span style="font-size:13px;font-weight:700;color:#38bdf8">📖 Guia de Mercados</span>
        <span style="color:#64748b">▲ fechar</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:1px;background:#334155">
        ${GLOSSARIO.map(g=>`
          <div style="background:#1e293b;padding:12px 14px">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">
              <span style="background:#0f172a;color:#38bdf8;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:700;font-family:monospace;flex-shrink:0">${g.cod}</span>
              <span style="font-weight:700;font-size:13px;color:#f1f5f9">${g.nome}</span>
            </div>
            <p style="font-size:12px;color:#94a3b8;line-height:1.6;margin:0">${g.desc}</p>
          </div>`).join('')}
      </div>
    </div>`;
}

// ── APOSTAS ──────────────────────────────────────────────────────────────────
function renderApostas() {
  const ligas = D.apostas_por_liga;
  const oddMin = D.odd_minima || 1.5;

  // Filtra: prob >= 55% E odd implícita >= 1.5 (prob <= ~66.7%)
  const temValor = a => (100 / a.prob) >= oddMin && a.prob >= 55;

  const labelsData = ['Todos', 'Hoje', 'Amanhã', ...D.datas.slice(2).map((_,i) =>
    new Date(D.datas[i+2]+'T12:00:00').toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'}))];

  const filtroHtml = `<div class="filtros">${labelsData.map(l =>
    `<button class="filtro-btn ${filtroData===l?'ativo':''}" onclick="setFiltro('${l}')">${l}</button>`
  ).join('')}</div>`;

  const totalValor = Object.values(ligas).flat().filter(temValor).length;

  const blocosHtml = Object.entries(ligas).map(([liga, apostas]) => {
    const filtradas = (filtroData === 'Todos' ? apostas : apostas.filter(a => a.data === filtroData))
      .filter(temValor);
    if (!filtradas.length) return '';

    const cards = filtradas.map(a => {
      const odd = (100 / a.prob).toFixed(2);
      const corProb = a.prob >= 65 ? 'verde' : 'amarelo';
      return `
      <div class="aposta ${a.prob>=65?'forte':'medio'}">
        <div class="logos">
          <img src="${a.home_logo}" alt="${a.home}">
          <img src="${a.away_logo}" alt="${a.away}">
        </div>
        <div class="aposta-info">
          <div class="aposta-partida">${a.home} × ${a.away}</div>
          <div class="aposta-mercado">${a.mercado}</div>
          <div style="font-size:11px;color:#64748b;margin-top:3px">${a.data} · ${a.horario} BRT</div>
        </div>
        <div class="aposta-meta">
          <div style="text-align:center">
            <div style="font-size:10px;color:#64748b;margin-bottom:3px">Chance de acerto</div>
            <div class="prob-badge ${a.prob>=65?'prob-forte':'prob-medio'}">${a.prob}%</div>
            <div style="font-size:11px;color:#64748b;margin-top:4px">odd mín. <strong style="color:#f1f5f9;font-size:13px">${odd}</strong></div>
          </div>
        </div>
      </div>`;
    }).join('');

    return `<div class="liga-bloco">
      <div class="liga-header">
        <span>${liga}</span>
        <span class="conta-badge">${filtradas.length} apostas</span>
      </div>
      ${cards}
    </div>`;
  }).filter(Boolean).join('');

  return `
    ${renderGlossario()}
    <div style="background:#0f172a;border:1px solid #334155;border-radius:8px;padding:10px 14px;font-size:12px;color:#64748b;display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px">
      <span>🎯 Apostas com <strong style="color:#38bdf8">odd ≥ ${oddMin}</strong> e chance entre 55–67% — equilíbrio entre confiança e valor</span>
      <span><strong style="color:#f1f5f9">${totalValor}</strong> apostas</span>
    </div>
    ${filtroHtml}
    ${blocosHtml || `<div class="vazio">📭 Nenhuma aposta com odd ≥ ${oddMin} para este filtro.</div>`}`;
}

function setFiltro(f) {
  filtroData = f;
  render();
}

// ── ANÁLISE ──────────────────────────────────────────────────────────────────
function renderJogo(j) {
  const p = j.probs;
  const live = ['1H','2H','HT','ET','P'].includes(j.status);
  const horarioBadge = live
    ? `<span class="status-live">⬤ AO VIVO</span>`
    : `<span class="horario">${j.horario} BRT</span>`;

  let body = `<div class="sem-probs">⚠️ Estatísticas insuficientes para este jogo.</div>`;
  if (p) {
    const maxR = Math.max(p.vc, p.emp, p.vf);
    body = `<div class="probs">
      <div class="resultado">${[
        {l:j.home.nome, v:p.vc,  c:cor(p.vc)},
        {l:'Empate',    v:p.emp, c:cor(p.emp)},
        {l:j.away.nome, v:p.vf,  c:cor(p.vf)},
      ].map(r=>`<div class="res-item">
        <div class="res-label" title="${r.l}">${r.l.split(' ')[0]}</div>
        <div class="res-valor ${r.c}">${r.v}%</div>
        <div class="res-bar"><div class="res-fill" style="width:${(r.v/maxR*100).toFixed(1)}%;background:${barC[r.c]}"></div></div>
      </div>`).join('')}
      </div>
      <div class="ou-grid">${[
        {l:'Over 1.5 gols', v:p.o15},
        {l:'Over 2.5 gols', v:p.o25},
        {l:'Over 3.5 gols', v:p.o35},
        {l:'Under 2.5 gols',v:p.u25},
        {l:'BTTS — Sim',    v:p.btts},
        {l:'BTTS — Não',    v:p.no_btts},
        {l:'Dupla 1X',      v:p.dc1x},
        {l:'Dupla X2',      v:p.dcx2},
        {l:'Over 9.5 cant.',v:p.o95},
      ].map(o=>`<div class="ou-item">
        <span class="ou-label">${o.l}</span>
        <span class="ou-val ${cor(o.v)}">${o.v}%</span>
      </div>`).join('')}
      </div>
      <div class="cant-row">
        <span>Over 10.5 cant.: <strong class="${cor(p.o105)}">${p.o105}%</strong> · Under 9.5: <strong class="${cor(p.u95)}">${p.u95}%</strong></span>
        <span>λ ${p.lam_c}×${p.lam_f} · cant. esp. <strong class="azul">${p.cant_media}</strong></span>
      </div>
      <div class="placares-row">${p.placares.map(x=>`
        <div class="plac">
          <span class="plac-score">${x.p}</span>
          <span class="plac-pct">${x.v}%</span>
        </div>`).join('')}
      </div>
    </div>`;
  }

  return `<div class="card">
    <div class="card-topo">
      <div class="times">
        <div class="time-bloco">
          <img src="${j.home.logo}" alt="${j.home.nome}" loading="lazy">
          <div class="time-nome">${j.home.nome}</div>
        </div>
        <span class="vs">VS</span>
        <div class="time-bloco">
          <img src="${j.away.logo}" alt="${j.away.nome}" loading="lazy">
          <div class="time-nome">${j.away.nome}</div>
        </div>
      </div>
      <div class="card-meta">
        <span class="data-tag">${j.data}</span>
        ${horarioBadge}
      </div>
    </div>
    ${body}
  </div>`;
}

function renderAnalise() {
  if (!D.total_jogos)
    return `<div class="vazio">📭 Nenhum jogo nos próximos 3 dias.</div>`;

  const filtroLabels = ['Todos', 'Hoje', 'Amanhã'];
  const filtroHtml = `<div class="filtros">${filtroLabels.map(l =>
    `<button class="filtro-btn ${filtroData===l?'ativo':''}" onclick="setFiltro('${l}')">${l}</button>`
  ).join('')}</div>`;

  const blocosHtml = Object.entries(D.ligas).map(([liga, jogos]) => {
    const filtrados = filtroData === 'Todos' ? jogos
      : jogos.filter(j => j.data === filtroData);
    if (!filtrados.length) return '';
    return `<div class="liga-bloco">
      <div class="liga-header"><span>${liga}</span><span class="conta-badge">${filtrados.length} jogos</span></div>
      <div style="display:flex;flex-direction:column;gap:12px">${filtrados.map(renderJogo).join('')}</div>
    </div>`;
  }).filter(Boolean).join('');

  return filtroHtml + (blocosHtml || `<div class="vazio">📭 Nenhum jogo para este filtro.</div>`);
}

// ── MÚLTIPLAS ─────────────────────────────────────────────────────────────────
function setFiltroMultiplas(d) { filtroMultiplas = d; render(); }

function renderMultiplas() {
  const multsDict = D.multiplas || {};
  const datas = Object.keys(multsDict);

  const aviso = `
    <div style="background:#1c1a05;border:1px solid #854d0e;border-radius:10px;padding:12px 16px;font-size:12px;color:#fbbf24;line-height:1.6">
      <strong>⚠️ Como funciona uma múltipla:</strong> você combina várias apostas em um único bilhete.
      A odd final é o <strong>produto</strong> das odds individuais — por isso cresce rápido.
      Mas a <strong>probabilidade de acerto cai</strong> a cada seleção adicionada (todas precisam ganhar).
      Use múltiplas de <strong>2 a 3 seleções</strong> com as de maior confiança.
    </div>`;

  if (!datas.length) return aviso + `<div class="vazio">📭 Apostas insuficientes para gerar múltiplas.</div>`;

  // Garante que filtroMultiplas aponta para uma data válida
  if (!multsDict[filtroMultiplas]) filtroMultiplas = datas[0];

  const filtroHtml = `<div class="filtros">${datas.map(d =>
    `<button class="filtro-btn ${filtroMultiplas===d?'ativo':''}" onclick="setFiltroMultiplas('${d}')">${d}</button>`
  ).join('')}</div>`;

  const mults = multsDict[filtroMultiplas] || [];
  if (!mults.length) return aviso + filtroHtml + `<div class="vazio">📭 Jogos insuficientes neste dia para gerar múltiplas.</div>`;

  const cards = mults.map(m => {
    const corOdd = m.odd_total >= 1.8 ? '#fbbf24' : '#34d399';
    const corProb = m.prob_total >= 30 ? '#34d399' : m.prob_total >= 20 ? '#fbbf24' : '#f87171';
    const sels = m.selecoes.map(s => `
      <div class="mult-sel">
        <div class="mult-sel-logos">
          <img src="${s.home_logo}" alt="${s.home}">
          <img src="${s.away_logo}" alt="${s.away}">
        </div>
        <div class="mult-sel-info">
          <div class="mult-sel-partida">${s.home} × ${s.away} · ${s.data} ${s.horario}</div>
          <div class="mult-sel-mercado">${s.mercado}</div>
        </div>
        <div class="mult-sel-odd">
          <div class="mult-sel-odd-val">${s.odd}</div>
          <div class="mult-sel-prob">${s.prob}%</div>
        </div>
      </div>`).join('');

    return `<div class="mult-card">
      <div class="mult-header">
        <span class="mult-n">${m.n} seleções</span>
        <div class="mult-odds">
          <div>
            <div style="font-size:10px;color:#64748b;text-align:right">Odd total</div>
            <div class="mult-odd-total" style="color:${corOdd}">${m.odd_total}</div>
          </div>
          <div>
            <div style="font-size:10px;color:#64748b">Prob. combinada</div>
            <div style="font-size:16px;font-weight:700;color:${corProb}">${m.prob_total}%</div>
          </div>
        </div>
      </div>
      <div class="mult-selecoes">${sels}</div>
      <div class="mult-footer">
        <span style="color:#64748b">R$100 apostados</span>
        <span>→ retorno: <span class="retorno">R$${(100 * m.odd_total).toFixed(0)}</span> (lucro: <span class="retorno">R$${(100 * m.odd_total - 100).toFixed(0)}</span>)</span>
      </div>
    </div>`;
  }).join('');

  return aviso + filtroHtml + `<div class="mult-grid">${cards}</div>`;
}

// ── VERIFICAR ─────────────────────────────────────────────────────────────────
function formaHtml(forma) {
  if (!forma) return '<span style="color:#475569;font-size:11px">sem dados</span>';
  return '<div class="forma-pills">' +
    forma.split('').map(c =>
      `<div class="pill pill-${c}" title="${c==='W'?'Vitória':c==='D'?'Empate':'Derrota'}">${c}</div>`
    ).join('') + '</div>';
}

function renderVerificarJogo(j, liga) {
  const v = j.verificar;
  if (!v) return `<div class="ver-card">
    <div class="ver-header">
      <div class="ver-match">
        <img src="${j.home.logo}"> ${j.home.nome} × ${j.away.nome} <img src="${j.away.logo}">
      </div>
      <span style="font-size:12px;color:#475569">${j.data} · ${j.horario} BRT</span>
    </div>
    <div style="padding:16px;font-size:13px;color:#475569;font-style:italic">⚠️ Dados insuficientes para verificação.</div>
  </div>`;

  const hs = v.home_stats, as_ = v.away_stats, po = v.poisson;
  const pct = (n, t) => t ? `${n} (${Math.round(n/t*100)}%)` : n;

  return `<div class="ver-card">
    <div class="ver-header">
      <div class="ver-match">
        <img src="${j.home.logo}"> ${j.home.nome} × ${j.away.nome} <img src="${j.away.logo}">
      </div>
      <span style="font-size:12px;color:#475569">${j.data} · ${j.horario} BRT · ${liga}</span>
    </div>
    <div class="ver-body">
      <div class="ver-col">
        <div class="ver-col-titulo"><img src="${j.home.logo}"> ${j.home.nome} <span style="color:#38bdf8">(Casa)</span></div>
        <div class="forma-pills">${formaHtml(hs.forma)}</div>
        <div class="ver-row"><span class="ver-lbl">Jogos na temporada</span><span class="ver-val">${hs.jogos_total} (${hs.jogos_casa} em casa)</span></div>
        <div class="ver-row"><span class="ver-lbl">Gols marcados/jogo (casa)</span><span class="ver-val verde">${hs.media_gols_marc}</span></div>
        <div class="ver-row"><span class="ver-lbl">Gols sofridos/jogo (casa)</span><span class="ver-val vermelho">${hs.media_gols_sofr}</span></div>
        <div class="ver-row"><span class="ver-lbl">Escanteios médios</span><span class="ver-val azul">${hs.escanteios}</span></div>
        <div class="ver-row"><span class="ver-lbl">Clean sheets</span><span class="ver-val">${pct(hs.clean_sheets, hs.jogos_total)}</span></div>
        <div class="ver-row"><span class="ver-lbl">Jogos sem marcar</span><span class="ver-val">${pct(hs.sem_marcar, hs.jogos_total)}</span></div>
      </div>
      <div class="ver-col">
        <div class="ver-col-titulo"><img src="${j.away.logo}"> ${j.away.nome} <span style="color:#f87171">(Fora)</span></div>
        <div class="forma-pills">${formaHtml(as_.forma)}</div>
        <div class="ver-row"><span class="ver-lbl">Jogos na temporada</span><span class="ver-val">${as_.jogos_total} (${as_.jogos_fora} fora)</span></div>
        <div class="ver-row"><span class="ver-lbl">Gols marcados/jogo (fora)</span><span class="ver-val verde">${as_.media_gols_marc}</span></div>
        <div class="ver-row"><span class="ver-lbl">Gols sofridos/jogo (fora)</span><span class="ver-val vermelho">${as_.media_gols_sofr}</span></div>
        <div class="ver-row"><span class="ver-lbl">Escanteios médios</span><span class="ver-val azul">${as_.escanteios}</span></div>
        <div class="ver-row"><span class="ver-lbl">Clean sheets</span><span class="ver-val">${pct(as_.clean_sheets, as_.jogos_total)}</span></div>
        <div class="ver-row"><span class="ver-lbl">Jogos sem marcar</span><span class="ver-val">${pct(as_.sem_marcar, as_.jogos_total)}</span></div>
      </div>
    </div>
    <div class="ver-poisson">
      <span>📐 <strong>Cálculo Poisson:</strong></span>
      <span>λ ${j.home.nome} = <code>${po.calc_c}</code> = <strong>${po.lam_c} gols esperados</strong></span>
      <span>λ ${j.away.nome} = <code>${po.calc_f}</code> = <strong>${po.lam_f} gols esperados</strong></span>
      <span style="color:#475569;font-size:11px">Fórmula: gols marcados × gols sofridos adversário (× 1.1 fator casa para mandante)</span>
    </div>
  </div>`;
}

function renderVerificar() {
  if (!D.total_jogos)
    return `<div class="vazio">📭 Nenhum jogo para verificar.</div>`;

  const filtroLabels = ['Todos', 'Hoje', 'Amanhã'];
  const filtroHtml = `<div class="filtros">${filtroLabels.map(l =>
    `<button class="filtro-btn ${filtroData===l?'ativo':''}" onclick="setFiltro('${l}')">${l}</button>`
  ).join('')}</div>`;

  const blocosHtml = Object.entries(D.ligas).map(([liga, jogos]) => {
    const filtrados = filtroData === 'Todos' ? jogos : jogos.filter(j => j.data === filtroData);
    if (!filtrados.length) return '';
    return `<div class="liga-bloco">
      <div class="liga-header"><span>${liga}</span><span class="conta-badge">${filtrados.length} jogos</span></div>
      ${filtrados.map(j => renderVerificarJogo(j, liga)).join('')}
    </div>`;
  }).filter(Boolean).join('');

  return filtroHtml + (blocosHtml || `<div class="vazio">📭 Nenhum jogo para este filtro.</div>`);
}

// ── Render principal ──────────────────────────────────────────────────────────
function render() {
  const html = tabAtual === 'apostas'   ? renderApostas()
             : tabAtual === 'multiplas' ? renderMultiplas()
             : tabAtual === 'analise'   ? renderAnalise()
             :                           renderVerificar();
  document.getElementById('app').innerHTML = html;
}

render();
</script>
</body>
</html>"""


def main():
    print(f"Datas: {', '.join(DATAS)} ({AGORA} BRT)")
    dados = gerar_dados()
    total_apostas = sum(len(v) for v in dados["apostas_por_liga"].values())
    print(f"\nTotal: {dados['total_jogos']} jogos · {total_apostas} apostas sugeridas")

    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(dados, ensure_ascii=False, cls=NumpyEncoder))
    out  = Path(__file__).parent.parent / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Gerado: {out}")


if __name__ == "__main__":
    main()
