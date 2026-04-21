import type { StatsTime } from "../types";

interface Props {
  nome: string;
  logo: string;
  stats: StatsTime;
  lado: "casa" | "fora";
}

export function CardStats({ nome, logo, stats, lado }: Props) {
  const gols_marcados = lado === "casa" ? stats.gols_marcados_media_casa : stats.gols_marcados_media_fora;
  const gols_sofridos = lado === "casa" ? stats.gols_sofridos_media_casa : stats.gols_sofridos_media_fora;

  return (
    <div style={cardStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <img src={logo} alt={nome} style={{ width: 40, height: 40, objectFit: "contain" }} />
        <div>
          <div style={{ fontWeight: 700, fontSize: 16, color: "#f1f5f9" }}>{nome}</div>
          <div style={{ fontSize: 12, color: "#64748b" }}>{lado === "casa" ? "Mandante" : "Visitante"}</div>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <Stat label="Gols marcados/jogo" value={gols_marcados} color="#34d399" />
        <Stat label="Gols sofridos/jogo" value={gols_sofridos} color="#f87171" />
        <Stat label="Escanteios marcados" value={stats.escanteios_marcados_media} color="#38bdf8" />
        <Stat label="Escanteios sofridos" value={stats.escanteios_sofridos_media} color="#fb923c" />
        <Stat label="Jogos na temporada" value={stats.jogos} color="#a78bfa" inteiro />
      </div>
    </div>
  );
}

function Stat({ label, value, color, inteiro = false }: { label: string; value: number; color: string; inteiro?: boolean }) {
  return (
    <div style={{ background: "#0f172a", borderRadius: 8, padding: "10px 12px" }}>
      <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color }}>{inteiro ? value : value.toFixed(2)}</div>
    </div>
  );
}

const cardStyle: React.CSSProperties = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: 12,
  padding: 20,
  flex: 1,
};
