#!/usr/bin/env python3
"""
Busca jogos do dia via API-Football, calcula probabilidades Poisson
e gera um index.html estático para o GitHub Pages.
"""

import os
import sys
import json
import time
import requests
import numpy as np
from scipy.stats import poisson
from datetime import datetime, timezone, timedelta
from pathlib import Path

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
if not API_KEY:
    print("ERRO: API_FOOTBALL_KEY não definida", file=sys.stderr)
    sys.exit(1)

BASE_URL = "https://v3.football.api-sports.io"
HEADERS  = {"x-apisports-key": API_KEY}

BRT   = timezone(timedelta(hours=-3))
HOJE  = datetime.now(BRT).strftime("%Y-%m-%d")
AGORA = datetime.now(BRT).strftime("%d/%m/%Y %H:%M")
ANO   = datetime.now(BRT).year
MES   = datetime.now(BRT).month

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

FATOR_CASA  = 1.1
MAX_GOLS    = 7
ULTIMOS_N   = 6   # partidas para calcular média de escanteios

# Cache em memória para evitar buscar o mesmo time duas vezes no mesmo run
_cache_stats:    dict = {}
_cache_corners:  dict = {}


def _temporada(liga_id: int) -> int:
    ligas_br = {71, 72, 73, 75}
    if liga_id in ligas_br:
        return ANO
    return ANO - 1 if MES < 7 else ANO


def _get(endpoint: str, params: dict) -> list | dict:
    time.sleep(0.3)
    r = requests.get(f"{BASE_URL}/{endpoint}", headers=HEADERS, params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("response", [])


def buscar_jogos(liga_id: int) -> list:
    return _get("fixtures", {"league": liga_id, "date": HOJE, "season": _temporada(liga_id)})


def buscar_stats(team_id: int, liga_id: int) -> dict | None:
    chave = (team_id, liga_id)
    if chave in _cache_stats:
        return _cache_stats[chave]
    data = _get("teams/statistics", {
        "team": team_id, "league": liga_id, "season": _temporada(liga_id),
    })
    result = data if data else None
    _cache_stats[chave] = result
    return result


def buscar_media_escanteios(team_id: int, liga_id: int) -> float:
    """Busca as últimas N partidas e calcula média de escanteios do time."""
    chave = (team_id, liga_id)
    if chave in _cache_corners:
        return _cache_corners[chave]

    fixtures = _get("fixtures", {
        "team": team_id, "league": liga_id,
        "season": _temporada(liga_id), "status": "FT", "last": ULTIMOS_N,
    })

    total_corners = 0
    n = 0
    for f in fixtures:
        fid = f["fixture"]["id"]
        stats = _get("fixtures/statistics", {"fixture": fid, "team": team_id})
        if stats:
            for s in stats[0].get("statistics", []):
                if s["type"] == "Corner Kicks" and s["value"] is not None:
                    total_corners += int(s["value"])
                    n += 1
                    break

    media = (total_corners / n) if n else 4.5  # fallback razoável
    _cache_corners[chave] = media
    return media


def extrair_medias(stats: dict, team_id: int, liga_id: int) -> dict:
    f = stats.get("fixtures", {})
    g = stats.get("goals", {})

    jogos_casa  = f.get("played", {}).get("home")  or 1
    jogos_fora  = f.get("played", {}).get("away")  or 1

    escanteios = buscar_media_escanteios(team_id, liga_id)

    return {
        "gols_marc_casa": (g.get("for",     {}).get("total", {}).get("home") or 0) / jogos_casa,
        "gols_marc_fora": (g.get("for",     {}).get("total", {}).get("away") or 0) / jogos_fora,
        "gols_sofr_casa": (g.get("against", {}).get("total", {}).get("home") or 0) / jogos_casa,
        "gols_sofr_fora": (g.get("against", {}).get("total", {}).get("away") or 0) / jogos_fora,
        "escanteios":     escanteios,
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
        [{"p": f"{i}x{j}", "v": round(mat[i][j] * 100, 1)}
         for i in range(MAX_GOLS) for j in range(MAX_GOLS)],
        key=lambda x: x["v"], reverse=True,
    )[:6]

    return {
        "lam_c":      round(lam_c, 2),
        "lam_f":      round(lam_f, 2),
        "vc":         round(vc  / tot * 100, 1),
        "emp":        round(emp / tot * 100, 1),
        "vf":         round(vf  / tot * 100, 1),
        "o15":        round((1 - float(np.sum(mat[:2, :2]))) * 100, 1),
        "o25":        round((1 - float(np.sum(mat[:3, :3]))) * 100, 1),
        "o35":        round((1 - float(np.sum(mat[:4, :4]))) * 100, 1),
        "btts":       round(float(np.sum(mat[1:, 1:])) * 100, 1),
        "cant_media": round(med_cant, 1),
        "o85":        round((1 - poisson.cdf(8,  med_cant)) * 100, 1),
        "o95":        round((1 - poisson.cdf(9,  med_cant)) * 100, 1),
        "o105":       round((1 - poisson.cdf(10, med_cant)) * 100, 1),
        "placares":   placares,
    }


def processar_liga(liga_id: int) -> list:
    print(f"  {LIGAS[liga_id]}...")
    try:
        fixtures = buscar_jogos(liga_id)
    except Exception as e:
        print(f"    ERRO fixtures: {e}", file=sys.stderr)
        return []

    jogos = []
    for f in fixtures:
        home   = f["teams"]["home"]
        away   = f["teams"]["away"]
        status = f["fixture"]["status"]["short"]

        try:
            dt_utc = datetime.fromisoformat(f["fixture"]["date"].replace("Z", "+00:00"))
            horario = dt_utc.astimezone(BRT).strftime("%H:%M")
        except Exception:
            horario = "--:--"

        print(f"    {home['name']} x {away['name']} ({horario})")

        try:
            stats_h = buscar_stats(home["id"], liga_id)
            stats_a = buscar_stats(away["id"], liga_id)
        except Exception as e:
            print(f"      ERRO stats: {e}", file=sys.stderr)
            stats_h = stats_a = None

        probs = None
        if stats_h and stats_a:
            try:
                mc    = extrair_medias(stats_h, home["id"], liga_id)
                mf    = extrair_medias(stats_a, away["id"], liga_id)
                probs = calcular_probs(mc, mf)
            except Exception as e:
                print(f"      ERRO probs: {e}", file=sys.stderr)

        jogos.append({
            "horario": horario,
            "status":  status,
            "home": {"id": home["id"], "nome": home["name"], "logo": home["logo"]},
            "away": {"id": away["id"], "nome": away["name"], "logo": away["logo"]},
            "probs": probs,
        })

    return jogos


def gerar_dados() -> dict:
    ligas_com_jogos: dict = {}
    total = 0
    for liga_id, nome in LIGAS.items():
        jogos = processar_liga(liga_id)
        if jogos:
            ligas_com_jogos[nome] = jogos
            total += len(jogos)
    return {"data": AGORA, "hoje": HOJE, "total": total, "ligas": ligas_com_jogos}


# ── HTML template ─────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>⚽ Apostas do Dia</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#0f172a;color:#f1f5f9;font-family:'Inter',system-ui,sans-serif;min-height:100vh;padding:0 0 48px}
header{background:#1e293b;border-bottom:1px solid #334155;padding:18px 16px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}
.logo{font-size:20px;font-weight:800}
.sub{font-size:12px;color:#64748b;margin-top:3px}
.badge{background:#0f172a;border:1px solid #334155;border-radius:20px;padding:4px 14px;font-size:12px;color:#64748b}
main{max-width:860px;margin:0 auto;padding:20px 16px;display:flex;flex-direction:column;gap:24px}
.liga-titulo{font-size:13px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:#94a3b8;padding-bottom:10px;border-bottom:1px solid #1e293b;margin-bottom:12px}
.jogos{display:flex;flex-direction:column;gap:12px}
.card{background:#1e293b;border:1px solid #334155;border-radius:12px;overflow:hidden}
.card-topo{display:flex;align-items:center;justify-content:space-between;padding:14px 16px 10px;gap:12px;flex-wrap:wrap}
.times{display:flex;align-items:center;gap:16px;flex:1;min-width:200px}
.time-bloco{display:flex;flex-direction:column;align-items:center;gap:5px;flex:1;text-align:center}
.time-bloco img{width:38px;height:38px;object-fit:contain}
.time-nome{font-size:13px;font-weight:600;line-height:1.2}
.vs{font-size:18px;font-weight:800;color:#475569;flex-shrink:0}
.horario{font-size:13px;color:#64748b;white-space:nowrap}
.status-live{color:#ef4444;font-weight:700;font-size:12px;animation:blink 1.2s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.4}}
.probs{padding:0 16px 14px;display:flex;flex-direction:column;gap:10px}
.resultado{display:flex;gap:8px}
.res-item{flex:1;background:#0f172a;border-radius:8px;padding:8px 6px;text-align:center}
.res-label{font-size:11px;color:#64748b;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.res-valor{font-size:19px;font-weight:700}
.res-bar{height:4px;border-radius:2px;margin-top:6px;background:#1e293b}
.res-fill{height:100%;border-radius:2px;transition:width .4s}
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
.verde{color:#34d399}.amarelo{color:#fbbf24}.vermelho{color:#f87171}.azul{color:#38bdf8}
@media(max-width:500px){.ou-grid{grid-template-columns:repeat(2,1fr)}.res-valor{font-size:16px}}
</style>
</head>
<body>
<script>window.DATA=__DATA__;</script>
<header>
  <div>
    <div class="logo">⚽ Apostas do Dia</div>
    <div class="sub">Poisson · Gols · Escanteios · Placares</div>
  </div>
  <div class="badge" id="badge-data"></div>
</header>
<main id="app"></main>
<script>
const D=window.DATA;
document.getElementById('badge-data').textContent='📅 '+D.hoje+' · atualizado '+D.data;

const cor=v=>v>=60?'verde':v>=40?'amarelo':'vermelho';
const barColor={'verde':'#34d399','amarelo':'#fbbf24','vermelho':'#f87171'};

function renderJogo(j){
  const p=j.probs;
  const live=j.status==='1H'||j.status==='2H'||j.status==='HT'||j.status==='ET'||j.status==='P';
  const horarioBadge=live
    ?`<span class="status-live">⬤ AO VIVO</span>`
    :`<span class="horario">${j.horario} BRT</span>`;

  let body=`<div class="sem-probs">⚠️ Estatísticas insuficientes para este jogo.</div>`;

  if(p){
    const maxR=Math.max(p.vc,p.emp,p.vf);
    const res=[
      {l:j.home.nome,v:p.vc, c:cor(p.vc)},
      {l:'Empate',   v:p.emp,c:cor(p.emp)},
      {l:j.away.nome,v:p.vf, c:cor(p.vf)},
    ];
    body=`<div class="probs">
      <div class="resultado">${res.map(r=>`
        <div class="res-item">
          <div class="res-label" title="${r.l}">${r.l.split(' ')[0]}</div>
          <div class="res-valor ${r.c}">${r.v}%</div>
          <div class="res-bar"><div class="res-fill" style="width:${(r.v/maxR*100).toFixed(1)}%;background:${barColor[r.c]}"></div></div>
        </div>`).join('')}
      </div>
      <div class="ou-grid">
        ${[
          {l:'Over 1.5 gols',v:p.o15},
          {l:'Over 2.5 gols',v:p.o25},
          {l:'Over 3.5 gols',v:p.o35},
          {l:'BTTS',         v:p.btts},
          {l:'Over 8.5 cant.',v:p.o85},
          {l:'Over 9.5 cant.',v:p.o95},
        ].map(o=>`<div class="ou-item">
          <span class="ou-label">${o.l}</span>
          <span class="ou-val ${cor(o.v)}">${o.v}%</span>
        </div>`).join('')}
      </div>
      <div class="cant-row">
        <span>Over 10.5 cant.: <strong class="${cor(p.o105)}">${p.o105}%</strong></span>
        <span>λ ${p.lam_c} × ${p.lam_f} · cant. esperados: <strong class="azul">${p.cant_media}</strong></span>
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
      ${horarioBadge}
    </div>
    ${body}
  </div>`;
}

function render(){
  if(!D.total){
    document.getElementById('app').innerHTML=`<div class="vazio">📭 Nenhum jogo encontrado para hoje (${D.hoje}) nas ligas monitoradas.</div>`;
    return;
  }
  document.getElementById('app').innerHTML=Object.entries(D.ligas).map(([liga,jogos])=>`
    <section>
      <div class="liga-titulo">${liga}</div>
      <div class="jogos">${jogos.map(renderJogo).join('')}</div>
    </section>`).join('');
}
render();
</script>
</body>
</html>"""


def main():
    print(f"Data: {HOJE} ({AGORA} BRT)")
    dados = gerar_dados()
    print(f"\nTotal: {dados['total']} jogos encontrados")

    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(dados, ensure_ascii=False))

    out = Path(__file__).parent.parent / "output" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Gerado: {out}")


if __name__ == "__main__":
    main()
