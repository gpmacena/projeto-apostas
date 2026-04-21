import type { Probabilidades } from "../types";

interface Props {
  probs: Probabilidades;
}

export function PainelOverUnder({ probs }: Props) {
  return (
    <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
      <Painel title="Over/Under Gols" cor="#34d399">
        <Linha label="Over 1.5" valor={probs.over_under_gols.over_1_5} />
        <Linha label="Over 2.5" valor={probs.over_under_gols.over_2_5} destaque />
        <Linha label="Over 3.5" valor={probs.over_under_gols.over_3_5} />
        <Linha label="BTTS (ambos marcam)" valor={probs.over_under_gols.btts} />
      </Painel>

      <Painel title="Over/Under Escanteios" cor="#38bdf8">
        <div style={{ fontSize: 12, color: "#64748b", marginBottom: 8 }}>
          Média total esperada: <strong style={{ color: "#38bdf8" }}>{probs.escanteios.media_total}</strong>
        </div>
        <Linha label="Over 7.5" valor={probs.escanteios.over_7_5} />
        <Linha label="Over 8.5" valor={probs.escanteios.over_8_5} />
        <Linha label="Over 9.5" valor={probs.escanteios.over_9_5} destaque />
        <Linha label="Over 10.5" valor={probs.escanteios.over_10_5} />
        <Linha label="Over 11.5" valor={probs.escanteios.over_11_5} />
      </Painel>
    </div>
  );
}

function Painel({ title, cor, children }: { title: string; cor: string; children: React.ReactNode }) {
  return (
    <div style={{ ...containerStyle, borderTop: `3px solid ${cor}`, flex: 1, minWidth: 220 }}>
      <h3 style={{ ...titleStyle, color: cor }}>{title}</h3>
      {children}
    </div>
  );
}

function Linha({ label, valor, destaque = false }: { label: string; valor: number; destaque?: boolean }) {
  const cor = valor >= 60 ? "#34d399" : valor >= 40 ? "#fbbf24" : "#f87171";
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "6px 0",
        borderBottom: "1px solid #1e293b",
        fontWeight: destaque ? 700 : 400,
        background: destaque ? "#0f172a" : "transparent",
        borderRadius: destaque ? 6 : 0,
        paddingLeft: destaque ? 8 : 0,
        paddingRight: destaque ? 8 : 0,
      }}
    >
      <span style={{ color: destaque ? "#f1f5f9" : "#94a3b8", fontSize: 14 }}>{label}</span>
      <span style={{ color: cor, fontSize: 16, fontWeight: 700 }}>{valor.toFixed(1)}%</span>
    </div>
  );
}

const containerStyle: React.CSSProperties = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: 12,
  padding: 20,
};

const titleStyle: React.CSSProperties = {
  margin: "0 0 14px",
  fontSize: 14,
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: 1,
};
