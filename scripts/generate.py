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
HEADERS = {"x-apisports-key": API_KEY}

BRT = timezone(timedelta(hours=-3))
HOJE = datetime.now(BRT).strftime("%Y-%m-%d")
AGORA = datetime.now(BRT).strftime("%d/%m/%Y %H:%M")
ANO = datetime.now(BRT).year
MES = datetime.now(BRT).month

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
MAX_GOLS = 7


def _temporada(liga_id: int) -> int:
    ligas_br = {71, 72, 73, 75}
    if liga_id in ligas_br:
        return ANO
    # Ligas europeias: temporada nova começa em julho/agosto
    return ANO - 1 if MES < 7 else ANO


def _get(endpoint: str, params: dict) -> list | dict:
    time.sleep(0.4)
    r = requests.get(f"{BASE_URL}/{endpoint}", headers=HEADERS, params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("response", [])


def buscar_jogos(liga_id: int) -> list:
    return _get("fixtures", {"league": liga_id, "date": HOJE, "season": _temporada(liga_id)})


def buscar_stats(team_id: int, liga_id: int) -> dict | None:
    data = _get("teams/statistics", {
        "team": team_id,
        "league": liga_id,
        "season": _temporada(liga_id),
    })
    return data if data else None


def _media_corners(corners_obj: dict, jogos: int) -> float:
    total = (corners_obj.get("total") or {})
    if isinstance(total, dict):
        soma = sum(v for v in total.values() if isinstance(v, (int, float)))
    else:
        soma = total or 0
    return soma / jogos if jogos else 0


def extrair_medias(stats: dict) -> dict:
    f = stats.get("fixtures", {})
    g = stats.get("goals", {})
    c = stats.get("corners") or {}

    jogos_casa = f.get("played", {}).get("home") or 1
    jogos_fora = f.get("played", {}).get("away") or 1
    jogos_total = f.get("played", {}).get("total") or 1

    return {
        "gols_marc_casa": (g.get("for", {}).get("total", {}).get("home") or 0) / jogos_casa,
        "gols_marc_fora": (g.get("for", {}).get("total", {}).get("away") or 0) / jogos_fora,
        "gols_sofr_casa": (g.get("against", {}).get("total", {}).get("home") or 0) / jogos_casa,
        "gols_sofr_fora": (g.get("against", {}).get("total", {}).get("away") or 0) / jogos_fora,
        "escanteios":     _media_corners(c.get("for") or {}, jogos_total),
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
        "lam_c": round(lam_c, 2),
        "lam_f": round(lam_f, 2),
        "vc":    round(vc  / tot * 100, 1),
        "emp":   round(emp / tot * 100, 1),
        "vf":    round(vf  / tot * 100, 1),
        "o15":   round((1 - float(np.sum(mat[:2, :2]))) * 100, 1),
        "o25":   round((1 - float(np.sum(mat[:3, :3]))) * 100, 1),
        "o35":   round((1 - float(np.sum(mat[:4, :4]))) * 100, 1),
        "btts":  round(float(np.sum(mat[1:, 1:])) * 100, 1),
        "cant_media": round(med_cant, 1),
        "o85":   round((1 - poisson.cdf(8,  med_cant)) * 100, 1),
        "o95":   round((1 - poisson.cdf(9,  med_cant)) * 100, 1),
        "o105":  round((1 - poisson.cdf(10, med_cant)) * 100, 1),
        "placares": placares,
    }


def processar_liga(liga_id: int) -> list:
    print(f"  Buscando {LIGAS[liga_id]}...")
    try:
        fixtures = buscar_jogos(liga_id)
    except Exception as e:
        print(f"    ERRO fixtures: {e}", file=sys.stderr)
        return []

    jogos = []
    for f in fixtures:
        home = f["teams"]["home"]
        away = f["teams"]["away"]
        kickoff_utc = f["fixture"]["date"]  # ISO 8601
        status = f["fixture"]["status"]["short"]

        # Converte horário para BRT
        try:
            dt_utc = datetime.fromisoformat(kickoff_utc.replace("Z", "+00:00"))
            dt_brt = dt_utc.astimezone(BRT)
            horario = dt_brt.strftime("%H:%M")
        except Exception:
            horario = "--:--"

        print(f"    {home['name']} x {away['name']} ({horario} BRT) — buscando stats...")

        try:
            stats_h_raw = buscar_stats(home["id"], liga_id)
            stats_a_raw = buscar_stats(away["id"], liga_id)
        except Exception as e:
            print(f"      ERRO stats: {e}", file=sys.stderr)
            stats_h_raw = stats_a_raw = None

        if not stats_h_raw or not stats_a_raw:
            probs = None
        else:
            mc = extrair_medias(stats_h_raw)
            mf = extrair_medias(stats_a_raw)
            probs = calcular_probs(mc, mf)

        jogos.append({
            "horario": horario,
            "status":  status,
            "home": {"id": home["id"], "nome": home["name"], "logo": home["logo"]},
            "away": {"id": away["id"], "nome": away["name"], "logo": away["logo"]},
            "probs": probs,
        })

    return jogos


def gerar_dados() -> dict:
    ligas_com_jogos = {}
    total_jogos = 0

    for liga_id, nome in LIGAS.items():
        jogos = processar_liga(liga_id)
        if jogos:
            ligas_com_jogos[nome] = jogos
            total_jogos += len(jogos)

    return {
        "data": AGORA,
        "hoje": HOJE,
        "total": total_jogos,
        "ligas": ligas_com_jogos,
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>⚽ Apostas do Dia</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#0f172a;color:#f1f5f9;font-family:'Inter',system-ui,sans-serif;min-height:100vh;padding:0 0 40px}
a{color:inherit;text-decoration:none}
header{background:#1e293b;border-bottom:1px solid #334155;padding:20px 16px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}
.logo{font-size:20px;font-weight:800}
.sub{font-size:12px;color:#64748b;margin-top:3px}
.badge{background:#0f172a;border:1px solid #334155;border-radius:20px;padding:4px 12px;font-size:12px;color:#64748b}
main{max-width:860px;margin:0 auto;padding:20px 16px;display:flex;flex-direction:column;gap:24px}
.liga-titulo{font-size:14px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#94a3b8;padding:0 0 10px;border-bottom:1px solid #1e293b;margin-bottom:12px}
.jogos{display:flex;flex-direction:column;gap:12px}
.card{background:#1e293b;border:1px solid #334155;border-radius:12px;overflow:hidden}
.card-topo{display:flex;align-items:center;justify-content:space-between;padding:14px 16px 10px;gap:12px;flex-wrap:wrap}
.times{display:flex;align-items:center;gap:16px;flex:1;min-width:200px}
.time-bloco{display:flex;flex-direction:column;align-items:center;gap:5px;flex:1;text-align:center}
.time-bloco img{width:36px;height:36px;object-fit:contain}
.time-nome{font-size:13px;font-weight:600;line-height:1.2}
.vs{font-size:18px;font-weight:800;color:#475569}
.horario{font-size:13px;color:#64748b;white-space:nowrap}
.status-live{color:#ef4444;font-weight:700;font-size:12px}
.probs{padding:0 16px 14px;display:flex;flex-direction:column;gap:10px}
.resultado{display:flex;gap:8px}
.res-item{flex:1;background:#0f172a;border-radius:8px;padding:8px 6px;text-align:center}
.res-label{font-size:11px;color:#64748b;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.res-valor{font-size:18px;font-weight:700}
.res-bar{height:4px;border-radius:2px;margin-top:6px;background:#334155}
.res-fill{height:100%;border-radius:2px}
.ou-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
.ou-item{background:#0f172a;border-radius:6px;padding:7px 8px;display:flex;justify-content:space-between;align-items:center}
.ou-label{font-size:11px;color:#94a3b8}
.ou-val{font-size:13px;font-weight:700}
.placares-row{display:flex;gap:6px;flex-wrap:wrap}
.plac{background:#0f172a;border-radius:6px;padding:5px 10px;font-size:12px;display:flex;flex-direction:column;align-items:center;gap:2px}
.plac-score{font-weight:700;color:#f1f5f9}
.plac-pct{color:#64748b;font-size:11px}
.sem-probs{font-size:12px;color:#475569;padding:0 16px 14px;font-style:italic}
.vazio{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:32px;text-align:center;color:#475569;font-size:14px}
.cant-info{font-size:11px;color:#475569;text-align:right;padding:0 16px 10px;margin-top:-6px}
.verde{color:#34d399} .amarelo{color:#fbbf24} .vermelho{color:#f87171} .azul{color:#38bdf8}
@media(max-width:500px){.ou-grid{grid-template-columns:repeat(2,1fr)}.res-item{padding:6px 4px}.res-valor{font-size:15px}}
</style>
</head>
<body>
<script>window.DATA=__DATA__;</script>
<header>
  <div>
    <div class="logo">⚽ Apostas do Dia</div>
    <div class="sub">Probabilidades via Distribuição de Poisson</div>
  </div>
  <div class="badge" id="atualizado"></div>
</header>
<main id="app"></main>
<script>
const D = window.DATA;
document.getElementById('atualizado').textContent = 'Atualizado: ' + D.data;

function cor(v){return v>=60?'verde':v>=40?'amarelo':'vermelho'}

function renderJogo(j){
  const p = j.probs;
  const horarioBadge = j.status==='1H'||j.status==='2H'||j.status==='HT'
    ? `<span class="status-live">● AO VIVO</span>`
    : `<span class="horario">${j.horario} BRT</span>`;

  let probsHtml = `<div class="sem-probs">Estatísticas insuficientes para calcular probabilidades.</div>`;

  if(p){
    const maxRes = Math.max(p.vc, p.emp, p.vf);
    probsHtml = `
      <div class="probs">
        <div class="resultado">
          ${[
            {l: j.home.nome.split(' ')[0], v: p.vc,  c:'verde'},
            {l: 'Empate',                  v: p.emp, c:'amarelo'},
            {l: j.away.nome.split(' ')[0], v: p.vf,  c:'vermelho'},
          ].map(r=>`
            <div class="res-item">
              <div class="res-label">${r.l}</div>
              <div class="res-valor ${r.c}">${r.v}%</div>
              <div class="res-bar"><div class="res-fill" style="width:${r.v/maxRes*100}%;background:currentColor" class="${r.c}"></div></div>
            </div>`).join('')}
        </div>

        <div class="ou-grid">
          ${[
            {l:'Over 1.5 gols', v:p.o15},
            {l:'Over 2.5 gols', v:p.o25},
            {l:'Over 3.5 gols', v:p.o35},
            {l:'BTTS',          v:p.btts},
            {l:'Over 8.5 cant.',v:p.o85},
            {l:'Over 9.5 cant.',v:p.o95},
          ].map(o=>`
            <div class="ou-item">
              <span class="ou-label">${o.l}</span>
              <span class="ou-val ${cor(o.v)}">${o.v}%</span>
            </div>`).join('')}
        </div>

        <div class="cant-info">Média escanteios esperada: ${p.cant_media} | λ ${p.lam_c} × ${p.lam_f}</div>

        <div class="placares-row">
          ${p.placares.map(x=>`
            <div class="plac">
              <span class="plac-score">${x.p}</span>
              <span class="plac-pct">${x.v}%</span>
            </div>`).join('')}
        </div>
      </div>`;
  }

  return `
    <div class="card">
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
      ${probsHtml}
    </div>`;
}

function renderApp(){
  if(D.total===0){
    document.getElementById('app').innerHTML=`<div class="vazio">📭 Nenhum jogo encontrado para hoje (${D.hoje}) nas ligas monitoradas.</div>`;
    return;
  }
  const html = Object.entries(D.ligas).map(([liga, jogos])=>`
    <section>
      <div class="liga-titulo">${liga}</div>
      <div class="jogos">${jogos.map(renderJogo).join('')}</div>
    </section>`).join('');
  document.getElementById('app').innerHTML = html;

  // fix: as barras de resultado usam currentColor mas precisam da cor da classe
  document.querySelectorAll('.res-fill').forEach(el=>{
    const parent = el.closest('.res-item');
    if(parent.querySelector('.verde')) el.style.background='#34d399';
    else if(parent.querySelector('.amarelo')) el.style.background='#fbbf24';
    else el.style.background='#f87171';
  });
}

renderApp();
</script>
</body>
</html>"""


def main():
    print(f"Gerando jogos para {HOJE} ({AGORA} BRT)...")
    dados = gerar_dados()
    print(f"Total de jogos encontrados: {dados['total']}")

    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(dados, ensure_ascii=False))

    output_dir = Path(__file__).parent.parent / "output"
    output_dir.mkdir(exist_ok=True)
    out_file = output_dir / "index.html"
    out_file.write_text(html, encoding="utf-8")
    print(f"Arquivo gerado: {out_file}")


if __name__ == "__main__":
    main()
