#!/usr/bin/env python3
"""Busca e analisa os dois jogos da Libertadores 29/04."""
import httpx, time, json, math, itertools
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
from scipy.stats import poisson

API_KEY = "516a897a31f38165273fc15f233e73a6"
BASE    = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}
BRT     = timezone(timedelta(hours=-3))

FATOR_CASA   = 1.10
MAX_GOLS     = 7
ULTIMOS_N    = 6

def get(endpoint, params):
    r = httpx.get(f"{BASE}/{endpoint}", headers=HEADERS, params=params, timeout=15)
    r.raise_for_status()
    time.sleep(0.35)
    return r.json().get("response", [])

def buscar_stats(team_id, liga_id, season):
    r = get("teams/statistics", {"team": team_id, "league": liga_id, "season": season})
    return r if r else None

def buscar_escanteios(team_id, liga_id, season):
    fixtures = get("fixtures", {
        "team": team_id, "league": liga_id,
        "season": season, "status": "FT", "last": ULTIMOS_N,
    })
    total, n = 0, 0
    for f in fixtures:
        stats = get("fixtures/statistics", {"fixture": f["fixture"]["id"], "team": team_id})
        if stats:
            for s in stats[0].get("statistics", []):
                if s["type"] == "Corner Kicks" and s["value"] is not None:
                    total += int(s["value"]); n += 1; break
    return total / n if n else 4.5

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
        [{"p": f"{i}x{j}", "v": round(mat[i][j]*100,1)} for i in range(MAX_GOLS) for j in range(MAX_GOLS)],
        key=lambda x: x["v"], reverse=True)[:6]
    return {
        "lam_c": round(lam_c, 2), "lam_f": round(lam_f, 2),
        "vc":  round(vc/tot*100,1), "emp": round(emp/tot*100,1), "vf": round(vf/tot*100,1),
        "dc1x": round((vc+emp)/tot*100,1), "dcx2": round((emp+vf)/tot*100,1),
        "o15":  round((1-float(np.sum(mat[:2,:2])))*100,1),
        "o25":  round((1-float(np.sum(mat[:3,:3])))*100,1),
        "o35":  round((1-float(np.sum(mat[:4,:4])))*100,1),
        "u25":  round(float(np.sum(mat[:3,:3]))*100,1),
        "btts": round(float(np.sum(mat[1:,1:]))*100,1),
        "no_btts": round(float(1-np.sum(mat[1:,1:]))*100,1),
        "cant_media": round(med_cant,1),
        "o85":  round((1-poisson.cdf(8,med_cant))*100,1),
        "o95":  round((1-poisson.cdf(9,med_cant))*100,1),
        "o105": round((1-poisson.cdf(10,med_cant))*100,1),
        "u95":  round(poisson.cdf(9,med_cant)*100,1),
        "placares": placares,
    }

# Busca fixture exato e horário BRT
LIGA_ID = 13
SEASON  = 2026
DATAS   = ["2026-04-28", "2026-04-29"]

fixtures_alvo = {}
for data in DATAS:
    fix = get("fixtures", {"league": LIGA_ID, "season": SEASON, "date": data})
    for f in fix:
        home_id = f["teams"]["home"]["id"]
        away_id = f["teams"]["away"]["id"]
        # Identifica os dois jogos
        if (home_id == 2546 and away_id == 1135) or (home_id == 1135 and away_id == 2546):
            fixtures_alvo["cristal_junior"] = f
        if (home_id == 1142 and away_id == 2330) or (home_id == 2330 and away_id == 1142):
            fixtures_alvo["tolima_coquimbo"] = f

print(f"Fixtures encontrados: {list(fixtures_alvo.keys())}\n")

JOGOS_PROCESSADOS = []

for chave, f in fixtures_alvo.items():
    home = f["teams"]["home"]
    away = f["teams"]["away"]
    dt_utc = datetime.fromisoformat(f["fixture"]["date"].replace("Z", "+00:00"))
    horario_brt = dt_utc.astimezone(BRT)
    horario_str = horario_brt.strftime("%H:%M")
    data_str    = horario_brt.strftime("%Y-%m-%d")
    data_label  = "Hoje" if data_str == datetime.now(BRT).strftime("%Y-%m-%d") else "Amanhã"

    print(f"{'='*60}")
    print(f"  {home['name']} vs {away['name']}")
    print(f"  {data_label} às {horario_str} BRT  |  {data_str}")
    print(f"  fixture_id={f['fixture']['id']}")

    sh = buscar_stats(home["id"], LIGA_ID, SEASON)
    sa = buscar_stats(away["id"], LIGA_ID, SEASON)

    probs, mc, mf = None, None, None
    verificar = None

    if sh and sa:
        mc = extrair_medias(sh, home["id"], LIGA_ID, SEASON)
        mf = extrair_medias(sa, away["id"], LIGA_ID, SEASON)
        probs = calcular_probs(mc, mf)
        print(f"  λ casa={probs['lam_c']}  λ fora={probs['lam_f']}")
        print(f"  1={probs['vc']}%  X={probs['emp']}%  2={probs['vf']}%")
        print(f"  Over 1.5={probs['o15']}%  Over 2.5={probs['o25']}%  BTTS={probs['btts']}%")
        tops = ", ".join(f"{x['p']}({x['v']}%)" for x in probs["placares"])
        print(f"  Placares: {tops}")
        verificar = {
            "home_stats": {
                "jogos_total": mc["jogos_total"], "jogos_casa": mc["jogos_casa"],
                "media_gols_marc": mc["media_gols_marc_casa"],
                "media_gols_sofr": mc["media_gols_sofr_casa"],
                "escanteios": round(mc["escanteios"],1),
                "clean_sheets": mc["clean_sheets"], "sem_marcar": mc["sem_marcar"],
                "forma": mc["forma"],
            },
            "away_stats": {
                "jogos_total": mf["jogos_total"], "jogos_fora": mf["jogos_fora"],
                "media_gols_marc": mf["media_gols_marc_fora"],
                "media_gols_sofr": mf["media_gols_sofr_fora"],
                "escanteios": round(mf["escanteios"],1),
                "clean_sheets": mf["clean_sheets"], "sem_marcar": mf["sem_marcar"],
                "forma": mf["forma"],
            },
            "poisson": {
                "lam_c": probs["lam_c"], "lam_f": probs["lam_f"],
                "calc_c": f"{round(mc['gols_marc_casa'],2)} × {round(mf['gols_sofr_fora'],2)} × {FATOR_CASA}",
                "calc_f": f"{round(mf['gols_marc_fora'],2)} × {round(mc['gols_sofr_casa'],2)}",
            },
        }
    else:
        print("  ⚠️ sem stats na Libertadores 2026 — tentando ligas locais...")
        # fallback: busca stats na liga local de cada time
        LIGAS_LOCAL = {2546: 281, 1135: 239, 1142: 239, 2330: 265}
        sl = LIGAS_LOCAL.get(home["id"])
        al = LIGAS_LOCAL.get(away["id"])
        if sl and al:
            sh2 = buscar_stats(home["id"], sl, SEASON)
            sa2 = buscar_stats(away["id"], al, SEASON)
            if sh2 and sa2:
                mc = extrair_medias(sh2, home["id"], sl, SEASON)
                mf = extrair_medias(sa2, away["id"], al, SEASON)
                probs = calcular_probs(mc, mf)
                print(f"  (usando ligas locais)  λ={probs['lam_c']} vs {probs['lam_f']}")
                print(f"  1={probs['vc']}%  X={probs['emp']}%  2={probs['vf']}%")
                print(f"  Over 2.5={probs['o25']}%  BTTS={probs['btts']}%")
                verificar = {
                    "home_stats": {
                        "jogos_total": mc["jogos_total"], "jogos_casa": mc["jogos_casa"],
                        "media_gols_marc": mc["media_gols_marc_casa"],
                        "media_gols_sofr": mc["media_gols_sofr_casa"],
                        "escanteios": round(mc["escanteios"],1),
                        "clean_sheets": mc["clean_sheets"], "sem_marcar": mc["sem_marcar"],
                        "forma": mc["forma"],
                    },
                    "away_stats": {
                        "jogos_total": mf["jogos_total"], "jogos_fora": mf["jogos_fora"],
                        "media_gols_marc": mf["media_gols_marc_fora"],
                        "media_gols_sofr": mf["media_gols_sofr_fora"],
                        "escanteios": round(mf["escanteios"],1),
                        "clean_sheets": mf["clean_sheets"], "sem_marcar": mf["sem_marcar"],
                        "forma": mf["forma"],
                    },
                    "poisson": {
                        "lam_c": probs["lam_c"], "lam_f": probs["lam_f"],
                        "calc_c": f"{round(mc['gols_marc_casa'],2)} × {round(mf['gols_sofr_fora'],2)} × {FATOR_CASA}",
                        "calc_f": f"{round(mf['gols_marc_fora'],2)} × {round(mc['gols_sofr_casa'],2)}",
                    },
                }
            else:
                print("  ⚠️ sem dados nem nas ligas locais")
        else:
            print("  ⚠️ ligas locais não mapeadas")

    JOGOS_PROCESSADOS.append({
        "chave": chave,
        "data": data_label, "data_iso": data_str, "horario": horario_str,
        "status": "NS",
        "home": {"id": home["id"], "nome": home["name"], "logo": home["logo"]},
        "away": {"id": away["id"], "nome": away["name"], "logo": away["logo"]},
        "probs": probs, "verificar": verificar,
    })

print(f"\n✅ {len(JOGOS_PROCESSADOS)} jogos processados")

# Salva resultado intermediário para usar no gerador
Path("scripts/_libertadores_jogos.json").write_text(
    json.dumps(JOGOS_PROCESSADOS, ensure_ascii=False, indent=2,
               default=lambda o: float(o) if isinstance(o, np.floating) else int(o) if isinstance(o, np.integer) else o)
)
print("💾 Dados salvos em scripts/_libertadores_jogos.json")
