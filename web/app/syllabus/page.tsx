"use client";
import { useEffect, useState } from "react";
import { api, useApi } from "@/lib/api";

type Topic = { name: string; unit?: string; weight: number; corpus_count?: number; figure_rate?: number; enabled?: boolean; generator?: string };
type S = { text: string; data: { _source?: string; sections: Record<string, { topics: Topic[] }> } };

export default function Syllabus() {
  const { data, error, setData } = useApi<S>("/syllabus");
  const [text, setText] = useState("");
  const [msg, setMsg] = useState("");
  const [tab, setTab] = useState("");
  useEffect(() => { if (data) { setText(data.text); setTab(t => t || Object.keys(data.data.sections)[0]); } }, [data]);

  async function run(path: string, body?: object) {
    setMsg("");
    try { const d = await api<S>(path, body ? { json: body } : { method: "POST" }); setData(d); setMsg(path.endsWith("rebuild") ? "Rebuilt from past papers." : "Saved."); }
    catch (e) { setMsg((e as Error).message); }
  }
  if (error) return <p className="alert">{error}</p>;
  if (!data) return <p className="loading">Loading…</p>;
  const topics = [...(data.data.sections[tab]?.topics ?? [])].sort((a, b) => b.weight - a.weight);
  const max = Math.max(...topics.map(t => t.weight), 0.0001);

  return (
    <div className="page">
      <h1>Syllabus and weights</h1>
      <p className="lede">The planner picks topics in each section in proportion to their weight. Set <code>enabled: false</code> to leave a topic out.</p>
      <div className="syl">
        <section>
          <div className="seg">{Object.keys(data.data.sections).map(s => <button key={s} aria-pressed={s === tab} onClick={() => setTab(s)}>{s}</button>)}</div>
          <ul className="weights">
            {topics.map(t => (
              <li key={t.name} className={t.enabled === false ? "off" : ""}>
                <div className="wname"><b>{t.name}</b><span>{t.unit}{t.generator ? `, ${t.generator}` : ""}</span></div>
                <div className="wbar"><span style={{ width: `${(t.weight / max) * 100}%` }} /></div>
                <div className="wnum num" title="weight">{t.weight.toFixed(3)}</div>
                <div className="wnum num dim" title="past questions, figure rate">{t.corpus_count ?? 0} Qs · {Math.round((t.figure_rate ?? 0) * 100)}% fig</div>
              </li>
            ))}
          </ul>
        </section>
        <section className="yaml">
          <label htmlFor="y">config/syllabus.yaml</label>
          <textarea id="y" spellCheck={false} value={text} onChange={e => setText(e.target.value)} />
          <div className="go">
            <button className="primary" onClick={() => run("/syllabus", { text })} disabled={text === data.text}>Save syllabus</button>
            <button onClick={() => confirm("Rebuild from past papers? This replaces your edits.") && run("/syllabus/rebuild")}>Rebuild from past papers</button>
          </div>
          {msg && <p className="hint" role="status">{msg}</p>}
        </section>
      </div>
    </div>
  );
}
