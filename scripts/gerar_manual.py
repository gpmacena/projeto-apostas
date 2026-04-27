#!/usr/bin/env python3
"""
Gera docs/index.html a partir de jogos informados manualmente.
Usa a mesma estrutura JSON e template HTML do generate.py.
"""

import json, time, sys, math, itertools
from pathlib import Path
from datetime import datetime, timezone, timedelta

import httpx
import numpy as np
from scipy.stats import poisson

# ── Config ─────────────────────────────────────────────────────────────────────
API_KEY = "516a897a31f38165273fc15f233e73a6"
BASE    = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

BRT       = timezone(timedelta(hours=-3))
AGORA     = datetime.now(BRT).strftime("%d/%m/%Y %H:%M")
HOJE_ISO  = datetime.now(BRT).strftime("%Y-%m-%d")
HOJE_DT   = datetime.now(BRT).strftime("%d/%m/%Y")

FATOR_CASA   = 1.10
MAX_GOLS     = 7
LIMIAR_FORTE = 68.0
LIMIAR_MEDIO = 55.0
ODD_MINIMA   = 1.50
ULTIMOS_N    = 6

# ── Jogos informados pelo usuário ──────────────────────────────────────────────
# (liga_id, liga_nome, home_id, away_id, horario, season)
JOGOS = [
    (135, "🇮🇹 Serie A",          490, 499, "13:30", 2025),  # Cagliari x Atalanta
    (203, "🇹🇷 Super Lig",         549, 3589,"14:00", 2025),  # Besiktas x Karagumruk
    (119, "🇩🇰 Superliga",         400, 395, "14:00", 2025),  # Copenhagen x Vejle
    (135, "🇮🇹 Serie A",          487, 494, "15:45", 2025),  # Lazio x Udinese
    (39,  "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League",  33,  55,  "16:00", 2025),  # Man United x Brentford
    (140, "🇪🇸 La Liga",          540, 539, "16:00", 2025),  # Espanyol x Levante
    (94,  "🇵🇹 Primeira Liga",     762, 4716,"16:15", 2025),  # Gil Vicente x Casa Pia
]

# ── API ────────────────────────────────────────────────────────────────────────
_cache = {}

def _get(endpoint, params):
    key = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
    if key in _cache:
        return _cache[key]
    time.sleep(0.35)
    r = httpx.get(f"{BASE}/{endpoint}", headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    data = r.json().get("response", [])
    _cache[key] = data
    return data

def buscar_info_time(team_id):
    r = _get("teams", {"id": team_id})
    if not r:
        return {"id": team_id, "nome": str(team_id), "logo": ""}
    t = r[0]["team"]
    return {"id": t["id"], "nome": t["name"], "logo": t["logo"]}

def buscar_stats(team_id, liga_id, season):
    r = _get("teams/statistics", {"team": team_id, "league": liga_id, "season": season})
    return r if r else None

def buscar_escanteios(team_id, liga_id, season):
    fixtures = _get("fixtures", {
        "team": team_id, "league": liga_id,
        "season": season, "status": "FT", "last": ULTIMOS_N,
    })
    total, n = 0, 0
    for f in fixtures:
        stats = _get("fixtures/statistics", {"fixture": f["fixture"]["id"], "team": team_id})
        if stats:
            for s in stats[0].get("statistics", []):
                if s["type"] == "Corner Kicks" and s["value"] is not None:
                    total += int(s["value"]); n += 1; break
    return total / n if n else 4.5

# ── Médias ─────────────────────────────────────────────────────────────────────
def extrair_medias(stats, team_id, liga_id, season):
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

    escanteios = buscar_escanteios(team_id, liga_id, season)

    return {
        "gols_marc_casa": gmc, "gols_marc_fora": gmf,
        "gols_sofr_casa": gsc, "gols_sofr_fora": gsf,
        "escanteios": escanteios,
        "jogos_total": jt, "jogos_casa": jc, "jogos_fora": jf,
        "clean_sheets": cs.get("total") or 0,
        "sem_marcar":   fs.get("total") or 0,
        "forma": (stats.get("form") or "")[-5:],
        "media_gols_marc_casa": round(gmc, 2),
        "media_gols_sofr_casa": round(gsc, 2),
        "media_gols_marc_fora": round(gmf, 2),
        "media_gols_sofr_fora": round(gsf, 2),
    }

# ── Poisson ────────────────────────────────────────────────────────────────────
def calcular_probs(mc, mf):
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
        [{"p": f"{i}x{j}", "v": round(mat[i][j] * 100, 1)}
         for i in range(MAX_GOLS) for j in range(MAX_GOLS)],
        key=lambda x: x["v"], reverse=True,
    )[:6]

    return {
        "lam_c": round(lam_c, 2), "lam_f": round(lam_f, 2),
        "vc":  round(vc  / tot * 100, 1),
        "emp": round(emp / tot * 100, 1),
        "vf":  round(vf  / tot * 100, 1),
        "dc1x": round((vc + emp) / tot * 100, 1),
        "dcx2": round((emp + vf) / tot * 100, 1),
        "o15": round((1 - float(np.sum(mat[:2, :2]))) * 100, 1),
        "o25": round((1 - float(np.sum(mat[:3, :3]))) * 100, 1),
        "o35": round((1 - float(np.sum(mat[:4, :4]))) * 100, 1),
        "u25": round(float(np.sum(mat[:3, :3])) * 100, 1),
        "btts": round(float(np.sum(mat[1:, 1:])) * 100, 1),
        "no_btts": round(float(1 - np.sum(mat[1:, 1:])) * 100, 1),
        "cant_media": round(med_cant, 1),
        "o85":  round((1 - poisson.cdf(8,  med_cant)) * 100, 1),
        "o95":  round((1 - poisson.cdf(9,  med_cant)) * 100, 1),
        "o105": round((1 - poisson.cdf(10, med_cant)) * 100, 1),
        "u95":  round(poisson.cdf(9, med_cant) * 100, 1),
        "placares": placares,
    }

# ── Apostas sugeridas por jogo ─────────────────────────────────────────────────
def extrair_apostas(jogo):
    p = jogo.get("probs")
    if not p:
        return []

    home = jogo["home"]["nome"]
    away = jogo["away"]["nome"]

    candidatas = [
        {"mercado": f"Vitória {home}",                  "prob": p["vc"],      "cod": "1"},
        {"mercado": f"Vitória {away}",                  "prob": p["vf"],      "cod": "2"},
        {"mercado": f"Dupla Chance: {home} ou Empate",  "prob": p["dc1x"],    "cod": "1X"},
        {"mercado": f"Dupla Chance: Empate ou {away}",  "prob": p["dcx2"],    "cod": "X2"},
        {"mercado": "Over 1.5 gols",                    "prob": p["o15"],     "cod": "O1.5"},
        {"mercado": "Over 2.5 gols",                    "prob": p["o25"],     "cod": "O2.5"},
        {"mercado": "Over 3.5 gols",                    "prob": p["o35"],     "cod": "O3.5"},
        {"mercado": "Under 2.5 gols",                   "prob": p["u25"],     "cod": "U2.5"},
        {"mercado": "BTTS — Ambos marcam",              "prob": p["btts"],    "cod": "BTTS"},
        {"mercado": "BTTS — Não",                       "prob": p["no_btts"], "cod": "BTTS-N"},
        {"mercado": "Over 8.5 escanteios",              "prob": p["o85"],     "cod": "O8.5C"},
        {"mercado": "Over 9.5 escanteios",              "prob": p["o95"],     "cod": "O9.5C"},
        {"mercado": "Over 10.5 escanteios",             "prob": p["o105"],    "cod": "O10.5C"},
        {"mercado": "Under 9.5 escanteios",             "prob": p["u95"],     "cod": "U9.5C"},
    ]

    sugeridas = [c for c in candidatas if c["prob"] >= LIMIAR_MEDIO]
    sugeridas.sort(key=lambda x: x["prob"], reverse=True)

    for s in sugeridas:
        s["forte"]     = s["prob"] >= LIMIAR_FORTE
        s["home"]      = home
        s["away"]      = away
        s["horario"]   = jogo["horario"]
        s["data"]      = jogo["data"]
        s["home_logo"] = jogo["home"]["logo"]
        s["away_logo"] = jogo["away"]["logo"]

    return sugeridas

# ── Múltiplas ──────────────────────────────────────────────────────────────────
def _to_sel(a):
    return {
        "mercado":   a["mercado"],
        "home":      a["home"],
        "away":      a["away"],
        "home_logo": a["home_logo"],
        "away_logo": a["away_logo"],
        "prob":      a["prob"],
        "odd":       round(100 / a["prob"], 2),
        "data":      a["data"],
        "horario":   a["horario"],
        "liga":      a.get("liga", ""),
    }

def gerar_multiplas(apostas_por_liga):
    todas = []
    for liga, apostas in apostas_por_liga.items():
        for a in apostas:
            todas.append({**a, "liga": liga})

    por_data = {}
    for a in todas:
        por_data.setdefault(a["data"], []).append(a)

    resultado = {}
    for data_label, apostas_dia in por_data.items():
        candidatas = [
            {**a, "odd_impl": round(100 / a["prob"], 3)}
            for a in apostas_dia if 65 <= a["prob"] <= 88
        ]
        if len(candidatas) < 2:
            continue

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
                    "n": r,
                    "odd_total": odd_total,
                    "prob_total": prob_total,
                    "selecoes": [_to_sel(a) for a in combo],
                })

        multiplas.sort(key=lambda x: (-x["prob_total"], x["odd_total"]))
        vistos = set()
        dedup = []
        for m in multiplas:
            chave = frozenset((s["home"], s["away"]) for s in m["selecoes"])
            if chave not in vistos:
                vistos.add(chave)
                dedup.append(m)
            if len(dedup) >= 12:
                break

        if dedup:
            resultado[data_label] = dedup

    return resultado

# ── Processamento principal ────────────────────────────────────────────────────
def processar():
    ligas = {}
    apostas_por_liga = {}

    for liga_id, liga_nome, home_id, away_id, horario, season in JOGOS:
        print(f"  {liga_nome}: buscando times e stats...", flush=True)

        home_info = buscar_info_time(home_id)
        away_info = buscar_info_time(away_id)
        print(f"    {home_info['nome']} vs {away_info['nome']}")

        sh = buscar_stats(home_id, liga_id, season)
        sa = buscar_stats(away_id, liga_id, season)

        probs, mc_data, mf_data = None, None, None
        verificar = None

        if sh and sa:
            mc = extrair_medias(sh, home_id, liga_id, season)
            mf = extrair_medias(sa, away_id, liga_id, season)
            probs = calcular_probs(mc, mf)
            mc_data, mf_data = mc, mf

            verificar = {
                "home_stats": {
                    "jogos_total":     mc["jogos_total"],
                    "jogos_casa":      mc["jogos_casa"],
                    "media_gols_marc": mc["media_gols_marc_casa"],
                    "media_gols_sofr": mc["media_gols_sofr_casa"],
                    "escanteios":      round(mc["escanteios"], 1),
                    "clean_sheets":    mc["clean_sheets"],
                    "sem_marcar":      mc["sem_marcar"],
                    "forma":           mc["forma"],
                },
                "away_stats": {
                    "jogos_total":     mf["jogos_total"],
                    "jogos_fora":      mf["jogos_fora"],
                    "media_gols_marc": mf["media_gols_marc_fora"],
                    "media_gols_sofr": mf["media_gols_sofr_fora"],
                    "escanteios":      round(mf["escanteios"], 1),
                    "clean_sheets":    mf["clean_sheets"],
                    "sem_marcar":      mf["sem_marcar"],
                    "forma":           mf["forma"],
                },
                "poisson": {
                    "lam_c":  probs["lam_c"],
                    "lam_f":  probs["lam_f"],
                    "calc_c": f"{round(mc['gols_marc_casa'],2)} × {round(mf['gols_sofr_fora'],2)} × {FATOR_CASA}",
                    "calc_f": f"{round(mf['gols_marc_fora'],2)} × {round(mc['gols_sofr_casa'],2)}",
                },
            }
            print(f"    λ={probs['lam_c']} vs {probs['lam_f']}  "
                  f"1={probs['vc']}% X={probs['emp']}% 2={probs['vf']}%")
        else:
            print("    ⚠️ sem stats")

        jogo = {
            "data":     "Hoje",
            "data_iso": HOJE_ISO,
            "horario":  horario,
            "status":   "NS",
            "home":     home_info,
            "away":     away_info,
            "probs":    probs,
            "verificar": verificar,
        }

        ligas.setdefault(liga_nome, []).append(jogo)

        if probs:
            apostas = extrair_apostas(jogo)
            apostas_por_liga.setdefault(liga_nome, []).extend(apostas)

    # ordena apostas por liga
    for liga in apostas_por_liga:
        apostas_por_liga[liga].sort(key=lambda x: x["prob"], reverse=True)
        apostas_por_liga[liga] = apostas_por_liga[liga][:20]

    total_jogos  = sum(len(v) for v in ligas.values())
    total_aposta = sum(len(v) for v in apostas_por_liga.values())

    dados = {
        "data":             AGORA,
        "hoje":             HOJE_DT,
        "datas":            [HOJE_ISO],
        "total_jogos":      total_jogos,
        "ligas":            ligas,
        "apostas_por_liga": apostas_por_liga,
        "odd_minima":       ODD_MINIMA,
        "multiplas":        gerar_multiplas(apostas_por_liga),
    }

    print(f"\n✅ {total_jogos} jogos · {total_aposta} apostas")
    return dados

# ── HTML (copiado do template do generate.py) ──────────────────────────────────
def carregar_template():
    gp = Path(__file__).parent / "generate.py"
    src = gp.read_text()
    start = src.index('HTML_TEMPLATE = r"""') + len('HTML_TEMPLATE = r"""')
    end   = src.index('"""', start)
    return src[start:end]

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):  return int(obj)
        if isinstance(obj, np.floating): return float(obj)
        if isinstance(obj, np.bool_):    return bool(obj)
        return super().default(obj)

def main():
    print(f"📅 {AGORA} BRT\n")
    dados    = processar()
    template = carregar_template()
    html     = template.replace("__DATA__", json.dumps(dados, ensure_ascii=False, cls=NumpyEncoder))

    out = Path(__file__).parent.parent / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"💾 Gerado: {out}")

if __name__ == "__main__":
    main()
