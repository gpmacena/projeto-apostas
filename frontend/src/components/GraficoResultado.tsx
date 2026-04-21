import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell, ResponsiveContainer } from "recharts";
import type { Probabilidades } from "../types";

interface Props {
  probs: Probabilidades;
  nomeCasa: string;
  nomeFora: string;
}

export function GraficoResultado({ probs, nomeCasa, nomeFora }: Props) {
  const dados = [
    { nome: nomeCasa.split(" ")[0], valor: probs.resultado.vitoria_casa, cor: "#34d399" },
    { nome: "Empate", valor: probs.resultado.empate, cor: "#fbbf24" },
    { nome: nomeFora.split(" ")[0], valor: probs.resultado.vitoria_fora, cor: "#f87171" },
  ];

  return (
    <div style={containerStyle}>
      <h3 style={titleStyle}>Resultado 1X2</h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={dados} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="nome" tick={{ fill: "#94a3b8", fontSize: 13 }} />
          <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }} domain={[0, 100]} unit="%" />
          <Tooltip
            formatter={(v) => [`${Number(v).toFixed(1)}%`, "Prob."]}
            contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }}
          />
          <Bar dataKey="valor" radius={[6, 6, 0, 0]}>
            {dados.map((d, i) => <Cell key={i} fill={d.cor} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div style={{ display: "flex", justifyContent: "center", gap: 24, marginTop: 8 }}>
        {dados.map((d) => (
          <div key={d.nome} style={{ textAlign: "center" }}>
            <div style={{ fontSize: 22, fontWeight: 700, color: d.cor }}>{d.valor.toFixed(1)}%</div>
            <div style={{ fontSize: 12, color: "#64748b" }}>{d.nome}</div>
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
