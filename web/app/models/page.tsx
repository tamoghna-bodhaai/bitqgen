"use client";
import { useApi } from "@/lib/api";

type Stage = { model: string; fallbacks?: string[]; reasoning?: string; tools?: string[] };
type M = { profiles: Record<string, Record<string, Stage>>; active: string };

export default function Models() {
  const { data, error } = useApi<M>("/models");
  return (
    <div className="page">
      <h1>Models</h1>
      <p className="lede">Which OpenRouter model runs each stage, from <code>config/models.yaml</code>. Edit that file to change them. Each paper can pick its own profile.</p>
      {error && <p className="alert">{error}</p>}
      {data && Object.entries(data.profiles).map(([name, stages]) => (
        <section key={name} className="profile">
          <h2>{name}{name === data.active && <span className="status t-good">Default</span>}</h2>
          <div className="tablewrap"><table className="t">
            <thead><tr><th>Stage</th><th>Model</th><th>Fallbacks</th><th>Reasoning</th><th>Tools</th></tr></thead>
            <tbody>{Object.entries(stages).map(([st, c]) => (
              <tr key={st}><td><b>{st}</b></td><td><code>{c.model}</code></td><td className="dim">{(c.fallbacks ?? []).join(", ")}</td>
                <td>{c.reasoning ?? ""}</td><td className="dim">{(c.tools ?? []).join(", ")}</td></tr>))}</tbody>
          </table></div>
        </section>
      ))}
    </div>
  );
}
