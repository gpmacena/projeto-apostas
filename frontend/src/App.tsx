import { useState } from "react";
import { BuscaTime } from "./components/BuscaTime";
import { CardStats } from "./components/CardStats";
import { GraficoResultado } from "./components/GraficoResultado";
import { PlacaresTabela } from "./components/PlacaresTabela";
import { PainelOverUnder } from "./components/PainelOverUnder";
import { analisarPartida } from "./api";
import type { Time, AnaliseResponse } from "./types";

const LIGAS = [
  { id: 71, nome: "Brasileirão Série A" },
  { id: 72, nome: "Brasileirão Série B" },
  { id: 2, nome: "Champions League" },
  { id: 3, nome: "Europa League" },
  { id: 39, nome: "Premier League" },
  { id: 140, nome: "La Liga" },
  { id: 135, nome: "Serie A (Itália)" },
  { id: 78, nome: "Bundesliga" },
];

export default function App() {
  const [timeCasa, setTimeCasa] = useState<Time | null>(null);
  const [timeFora, setTimeFora] = useState<Time | null>(null);
  const [leagueId, setLeagueId] = useState(71);
  const [season, setSeason] = useState(2024);
  const [analise, setAnalise] = useState<AnaliseResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function analisar() {
    if (!timeCasa || !timeFora) return;
    setLoading(true);
    setErro(null);
    setAnalise(null);
    try {
      const resultado = await analisarPartida(timeCasa.id, timeFora.id, leagueId, season);
      setAnalise(resultado);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Erro ao buscar análise.";
      setErro(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={layoutStyle}>
      <header style={headerStyle}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: "#f1f5f9" }}>
          ⚽ Analisador de Apostas
        </h1>
        <p style={{ margin: "4px 0 0", color: "#64748b", fontSize: 13 }}>
          Probabilidades via Distribuição de Poisson
        </p>
      </header>

      <div style={cardBase}>
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          <BuscaTime label="Time da Casa" onSelect={setTimeCasa} timeSelecionado={timeCasa} />
          <BuscaTime label="Time Visitante" onSelect={setTimeFora} timeSelecionado={timeFora} />
        </div>

        <div style={{ display: "flex", gap: 16, marginTop: 16, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div style={{ flex: 1, minWidth: 180 }}>
            <label style={labelStyle}>Liga</label>
            <select
              value={leagueId}
              onChange={(e) => setLeagueId(Number(e.target.value))}
              style={selectStyle}
            >
              {LIGAS.map((l) => (
                <option key={l.id} value={l.id}>{l.nome}</option>
              ))}
            </select>
          </div>
          <div style={{ width: 120 }}>
            <label style={labelStyle}>Temporada</label>
            <select
              value={season}
              onChange={(e) => setSeason(Number(e.target.value))}
              style={selectStyle}
            >
              {[2024, 2023, 2022].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <button
            onClick={analisar}
            disabled={!timeCasa || !timeFora || loading}
            style={btnStyle(!timeCasa || !timeFora || loading)}
          >
            {loading ? "Analisando..." : "Analisar Partida"}
          </button>
        </div>

        {erro && (
          <div style={{ marginTop: 12, padding: "10px 14px", background: "#450a0a", borderRadius: 8, color: "#fca5a5", fontSize: 14 }}>
            {erro}
          </div>
        )}
      </div>

      {analise && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ ...cardBase, textAlign: "center" }}>
            <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 20 }}>
              <TeamBadge nome={analise.time_casa.nome} logo={analise.time_casa.logo} />
              <span style={{ fontSize: 28, fontWeight: 800, color: "#475569" }}>VS</span>
              <TeamBadge nome={analise.time_fora.nome} logo={analise.time_fora.logo} />
            </div>
            <div style={{ fontSize: 12, color: "#475569", marginTop: 8 }}>
              λ casa: {analise.probabilidades.lambda_casa} · λ fora: {analise.probabilidades.lambda_fora}
            </div>
          </div>

          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            <CardStats
              nome={analise.time_casa.nome}
              logo={analise.time_casa.logo}
              stats={analise.estatisticas_casa}
              lado="casa"
            />
            <CardStats
              nome={analise.time_fora.nome}
              logo={analise.time_fora.logo}
              stats={analise.estatisticas_fora}
              lado="fora"
            />
          </div>

          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            <GraficoResultado
              probs={analise.probabilidades}
              nomeCasa={analise.time_casa.nome}
              nomeFora={analise.time_fora.nome}
            />
            <PlacaresTabela probs={analise.probabilidades} />
          </div>

          <PainelOverUnder probs={analise.probabilidades} />
        </div>
      )}
    </div>
  );
}

function TeamBadge({ nome, logo }: { nome: string; logo: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
      <img src={logo} alt={nome} style={{ width: 56, height: 56, objectFit: "contain" }} />
      <span style={{ fontWeight: 700, fontSize: 15, color: "#f1f5f9" }}>{nome}</span>
    </div>
  );
}

const layoutStyle: React.CSSProperties = {
  minHeight: "100vh",
  background: "#0f172a",
  color: "#f1f5f9",
  fontFamily: "'Inter', system-ui, sans-serif",
  padding: "20px 16px",
  maxWidth: 900,
  margin: "0 auto",
  display: "flex",
  flexDirection: "column",
  gap: 16,
};

const headerStyle: React.CSSProperties = {
  borderBottom: "1px solid #1e293b",
  paddingBottom: 16,
};

const cardBase: React.CSSProperties = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: 12,
  padding: 20,
};

const labelStyle: React.CSSProperties = {
  display: "block",
  marginBottom: 6,
  fontWeight: 600,
  color: "#94a3b8",
  fontSize: 14,
};

const selectStyle: React.CSSProperties = {
  width: "100%",
  padding: "10px 12px",
  background: "#0f172a",
  border: "1px solid #334155",
  borderRadius: 8,
  color: "#f1f5f9",
  fontSize: 14,
};

const btnStyle = (disabled: boolean): React.CSSProperties => ({
  padding: "11px 28px",
  background: disabled ? "#1e3a5f" : "linear-gradient(135deg, #3b82f6, #6366f1)",
  color: disabled ? "#475569" : "#fff",
  border: "none",
  borderRadius: 8,
  fontWeight: 700,
  fontSize: 15,
  cursor: disabled ? "not-allowed" : "pointer",
  whiteSpace: "nowrap",
  transition: "opacity 0.2s",
});
