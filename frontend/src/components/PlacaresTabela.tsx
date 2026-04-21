import type { Probabilidades } from "../types";

interface Props {
  probs: Probabilidades;
}

export function PlacaresTabela({ probs }: Props) {
  const max = probs.placares_top[0]?.prob ?? 1;

  return (
    <div style={containerStyle}>
      <h3 style={titleStyle}>Placares mais prováveis</h3>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {probs.placares_top.map((p) => (
          <div key={p.placar} style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ width: 40, textAlign: "center", fontWeight: 700, color: "#f1f5f9", fontSize: 15 }}>
              {p.placar}
            </span>
            <div style={{ flex: 1, background: "#0f172a", borderRadius: 4, height: 18, overflow: "hidden" }}>
              <div
                style={{
                  width: `${(p.prob / max) * 100}%`,
                  height: "100%",
                  background: "linear-gradient(90deg, #38bdf8, #6366f1)",
                  borderRadius: 4,
                  transition: "width 0.4s",
                }}
              />
            </div>
            <span style={{ width: 48, textAlign: "right", color: "#38bdf8", fontWeight: 600, fontSize: 13 }}>
              {p.prob.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

const containerStyle: React.CSSProperties = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: 12,
  padding: 20,
  flex: 1,
};

const titleStyle: React.CSSProperties = {
  margin: "0 0 16px",
  fontSize: 15,
  fontWeight: 700,
  color: "#94a3b8",
  textTransform: "uppercase",
  letterSpacing: 1,
};
