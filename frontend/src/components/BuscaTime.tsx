import { useState, useEffect, useRef } from "react";
import { buscarTimes } from "../api";
import type { Time } from "../types";

interface Props {
  label: string;
  onSelect: (time: Time) => void;
  timeSelecionado: Time | null;
}

export function BuscaTime({ label, onSelect, timeSelecionado }: Props) {
  const [query, setQuery] = useState("");
  const [resultados, setResultados] = useState<Time[]>([]);
  const [loading, setLoading] = useState(false);
  const [aberto, setAberto] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (query.length < 3) {
      setResultados([]);
      return;
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      setLoading(true);
      try {
        const times = await buscarTimes(query);
        setResultados(times);
        setAberto(true);
      } catch {
        setResultados([]);
      } finally {
        setLoading(false);
      }
    }, 400);
  }, [query]);

  function selecionar(time: Time) {
    onSelect(time);
    setQuery(time.nome);
    setAberto(false);
  }

  return (
    <div style={{ position: "relative", flex: 1 }}>
      <label style={{ display: "block", marginBottom: 6, fontWeight: 600, color: "#94a3b8" }}>
        {label}
      </label>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => resultados.length > 0 && setAberto(true)}
        placeholder="Digite o nome do time..."
        style={inputStyle}
      />
      {loading && <div style={dropdownStyle}>Buscando...</div>}
      {aberto && resultados.length > 0 && (
        <div style={dropdownStyle}>
          {resultados.map((t) => (
            <div key={t.id} onClick={() => selecionar(t)} style={itemStyle}>
              {t.logo && (
                <img src={t.logo} alt={t.nome} style={{ width: 22, height: 22, objectFit: "contain" }} />
              )}
              <span>{t.nome}</span>
              <span style={{ color: "#64748b", fontSize: 12 }}>{t.pais}</span>
            </div>
          ))}
        </div>
      )}
      {timeSelecionado && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
          <img src={timeSelecionado.logo} alt={timeSelecionado.nome} style={{ width: 28, height: 28 }} />
          <span style={{ color: "#38bdf8", fontWeight: 600 }}>{timeSelecionado.nome}</span>
        </div>
      )}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "10px 14px",
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: 8,
  color: "#f1f5f9",
  fontSize: 15,
  outline: "none",
  boxSizing: "border-box",
};

const dropdownStyle: React.CSSProperties = {
  position: "absolute",
  top: "100%",
  left: 0,
  right: 0,
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: 8,
  zIndex: 100,
  marginTop: 4,
  maxHeight: 240,
  overflowY: "auto",
};

const itemStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  padding: "10px 14px",
  cursor: "pointer",
  borderBottom: "1px solid #334155",
};
