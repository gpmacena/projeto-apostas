#!/usr/bin/env python3
"""Analisa jogos informados manualmente, consultando a API para stats."""

import os, sys, json, time
import httpx
import numpy as np
from scipy.stats import poisson

API_KEY = "516a897a31f38165273fc15f233e73a6"
BASE    = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

FATOR_CASA = 1.10
MAX_GOLS   = 7

# Temporada: ligas Sul-americanas usam ano corrente
def _season(liga_id):
    # Ligas sul-americanas: temporada = ano corrente (2026)
    if liga_id in {71, 72, 73, 75, 128, 239, 253}:
        return 2026
    # Ligas europeias: temporada 2025/26 = season 2025
    return 2025

def _get(endpoint, params):
    url = f"{BASE}/{endpoint}"
    r = httpx.get(url, headers=HEADERS, params=params, timeout=15)
    r.raise_for_status()
    time.sleep(0.3)   # respeita rate limit
    return r.json().get("response", [])

def buscar_time(nome):
    res = _get("teams", {"search": nome})
    return res

def buscar_stats(team_id, liga_id):
    res = _get("teams/statistics", {
        "team": team_id, "league": liga_id, "season": _season(liga_id)
    })
    return res if res else None

def buscar_escanteios(team_id, liga_id, n=6):
    fixtures = _get("fixtures", {
        "team": team_id, "league": liga_id,
        "season": _season(liga_id), "status": "FT", "last": n
    })
    if not fixtures:
        return 0.0
    total = 0
    count = 0
    for f in fixtures:
        stats = _get("fixtures/statistics", {"fixture": f["fixture"]["id"]})
        for ts in stats:
            if ts["team"]["id"] == team_id:
                for s in ts["statistics"]:
                    if s["type"] == "Corner Kicks" and s["value"] is not None:
                        total += int(s["value"])
                        count += 1
    return total / count if count else 0.0

def extrair_medias(stats, team_id, liga_id):
    fix = stats["fixtures"]
    goals = stats["goals"]
    j_casa = fix["played"]["home"] or 1
    j_fora = fix["played"]["away"] or 1
    return {
        "gols_marc_casa": (goals["for"]["total"]["home"] or 0) / j_casa,
        "gols_marc_fora": (goals["for"]["total"]["away"] or 0) / j_fora,
        "gols_sofr_casa": (goals["against"]["total"]["home"] or 0) / j_casa,
        "gols_sofr_fora": (goals["against"]["total"]["away"] or 0) / j_fora,
    }

def poisson_probs(lam_c, lam_f):
    mat = np.zeros((MAX_GOLS, MAX_GOLS))
    for i in range(MAX_GOLS):
        for j in range(MAX_GOLS):
            mat[i][j] = poisson.pmf(i, lam_c) * poisson.pmf(j, lam_f)
    vc = float(np.sum(np.tril(mat, -1)))
    em = float(np.sum(np.diag(mat)))
    vf = float(np.sum(np.triu(mat, 1)))
    tot = vc + em + vf
    vc /= tot; em /= tot; vf /= tot
    o15 = 1 - float(np.sum(mat[:2, :2]))
    o25 = 1 - float(np.sum(mat[:3, :3]))
    o35 = 1 - float(np.sum(mat[:4, :4]))
    btts = float(np.sum(mat[1:, 1:]))
    placares = sorted(
        [{"p": f"{i}x{j}", "prob": round(mat[i][j]*100,2)} for i in range(MAX_GOLS) for j in range(MAX_GOLS)],
        key=lambda x: x["prob"], reverse=True
    )
    return {
        "vc": round(vc*100,1), "em": round(em*100,1), "vf": round(vf*100,1),
        "o15": round(o15*100,1), "o25": round(o25*100,1), "o35": round(o35*100,1),
        "btts": round(btts*100,1),
        "top_placares": placares[:6],
    }

def odd_justa(prob_pct):
    if prob_pct <= 0: return 99.0
    return round(100 / prob_pct, 2)

def analisar_jogo(nome_casa, nome_fora, liga_id, odd_1, odd_x, odd_2):
    print(f"\n{'='*60}")
    print(f"  {nome_casa}  vs  {nome_fora}  (liga {liga_id})")
    print(f"{'='*60}")

    # busca times
    res_c = buscar_time(nome_casa)
    res_f = buscar_time(nome_fora)
    if not res_c or not res_f:
        print("  !! time não encontrado na API"); return None

    # pega primeiro resultado relevante
    tc = res_c[0]["team"]
    tf = res_f[0]["team"]
    print(f"  Casa : {tc['name']} (id {tc['id']})")
    print(f"  Fora : {tf['name']} (id {tf['id']})")

    sc = buscar_stats(tc["id"], liga_id)
    sf = buscar_stats(tf["id"], liga_id)
    if not sc or not sf:
        print("  !! stats não encontradas"); return None

    mc = extrair_medias(sc, tc["id"], liga_id)
    mf = extrair_medias(sf, tf["id"], liga_id)

    lam_c = max(mc["gols_marc_casa"] * mf["gols_sofr_fora"] * FATOR_CASA, 0.3)
    lam_f = max(mf["gols_marc_fora"] * mc["gols_sofr_casa"], 0.3)

    p = poisson_probs(lam_c, lam_f)

    print(f"\n  λ casa={lam_c:.2f}  λ fora={lam_f:.2f}")
    print(f"  1={p['vc']}%  X={p['em']}%  2={p['vf']}%")
    print(f"  Over 1.5={p['o15']}%  Over 2.5={p['o25']}%  Over 3.5={p['o35']}%  BTTS={p['btts']}%")
    tops = ", ".join(f"{x['p']}({x['prob']}%)" for x in p['top_placares'])
    print(f"  Placares: {tops}")

    # analisa value
    odds_book  = {"1": odd_1, "X": odd_x, "2": odd_2}
    probs_mod  = {"1": p["vc"], "X": p["em"], "2": p["vf"]}
    recomendacoes = []

    for k, prob in probs_mod.items():
        oj = odd_justa(prob)
        ob = odds_book[k]
        ev = (prob/100) * ob - 1
        if ob >= oj * 1.05:   # odd de mercado >= 5% acima da odd justa = value
            recomendacoes.append({
                "aposta": k, "prob_modelo": prob,
                "odd_justa": oj, "odd_mercado": ob,
                "ev": round(ev*100, 1),
                "confianca": "FORTE" if prob >= 60 else "MEDIA"
            })

    # over/under value (usa odd típica se não fornecida — só informa)
    print("\n  --- Recomendações ---")
    if recomendacoes:
        for r in recomendacoes:
            print(f"  ✅ {r['aposta']}  prob={r['prob_modelo']}%  odd_justa={r['odd_justa']}  "
                  f"odd_mercado={r['odd_mercado']}  EV=+{r['ev']}%  [{r['confianca']}]")
    else:
        print("  ❌ Nenhum value encontrado no 1X2 com odds informadas")

    return {"time_casa": tc["name"], "time_fora": tf["name"], "probs": p, "recomendacoes": recomendacoes}


# ── Jogos informados pelo usuário ─────────────────────────────────────────────

JOGOS = [
    # (nome_casa, nome_fora, liga_id, odd_1, odd_x, odd_2)
    ("Besiktas",           "Karagumruk",  203,  1.35, 5.10, 7.20),
    ("Gil Vicente",        "Casa Pia",     94,  1.70, 3.65, 5.30),
    ("Manchester United",  "Brentford",    39,  1.97, 3.70, 3.70),
    ("Cagliari",           "Atalanta",    135,  4.75, 3.80, 1.72),
    ("Lazio",              "Udinese",     135,  2.10, 3.15, 3.85),
    ("Espanyol",           "Levante",     140,  2.07, 3.25, 3.80),
    ("FC Copenhagen",      "Vejle",       119,  1.27, 5.90, 9.20),
    ("Athletic Club",      "Nautico",      72,  2.80, 3.05, 2.67),  # Série B
]

if __name__ == "__main__":
    resultados = []
    for jogo in JOGOS:
        r = analisar_jogo(*jogo)
        if r:
            resultados.append(r)

    print("\n\n" + "="*60)
    print("  RESUMO FINAL — APOSTAS COM VALUE")
    print("="*60)
    for r in resultados:
        if r["recomendacoes"]:
            for rec in r["recomendacoes"]:
                print(f"  {r['time_casa']} vs {r['time_fora']}  →  {rec['aposta']}  "
                      f"@{rec['odd_mercado']}  (modelo {rec['prob_modelo']}%, EV+{rec['ev']}%)")
