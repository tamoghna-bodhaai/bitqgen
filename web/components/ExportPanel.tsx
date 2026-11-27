"use client";
import { useState } from "react";

export default function ExportPanel({ base, sections }: { base: string; sections: string[] }) {
  const [content, setContent] = useState("paper");
  const [fmt, setFmt] = useState("pdf");
  const [chosen, setChosen] = useState<string[] | null>(null);
  const [instr, setInstr] = useState(true);
  const [key, setKey] = useState(true);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const sel = chosen ?? sections;
  const FMT: Record<string, string> = { pdf: "PDF", docx: "Word", html: "HTML" };

  async function go() {
    if (!sel.length) { setMsg("Pick at least one section."); return; }
    setBusy(true); setMsg("Rendering…");
    const q = new URLSearchParams({ content, fmt, sections: sel.length === sections.length ? "" : sel.join("|"),
      instructions: instr ? "1" : "0", answer_key: key ? "1" : "0" });
    try {
      const r = await fetch(`${base}/export?${q}`);
      if (!r.ok) throw new Error(await r.text());
      const blob = await r.blob();
      const name = decodeURIComponent((r.headers.get("content-disposition") || "").match(/filename\*?=(?:UTF-8'')?"?([^";]+)/)?.[1] || "export");
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; a.click();
      setMsg(`Downloaded ${name}`);
    } catch (e) { setMsg(`Export failed: ${(e as Error).message.slice(0, 200)}`); }
    setBusy(false);
  }

  return (
    <section className="export" id="export">
      <h2>Export</h2>
      <div className="seg" role="radiogroup" aria-label="Content">
        {[["paper", "Question paper"], ["solutions", "With solutions"], ["key", "Answer key"]].map(([v, l]) =>
          <button key={v} type="button" aria-pressed={content === v} onClick={() => setContent(v)}>{l}</button>)}
      </div>
      <div className="seg" role="radiogroup" aria-label="Format">
        {Object.entries(FMT).map(([v, l]) => <button key={v} type="button" aria-pressed={fmt === v} onClick={() => setFmt(v)}>{l}</button>)}
      </div>
      <div className="secs">
        {sections.map(s => (
          <label key={s} className="check"><input type="checkbox" checked={sel.includes(s)}
            onChange={e => setChosen(e.target.checked ? [...sel, s] : sel.filter(x => x !== s))} /> {s}</label>
        ))}
      </div>
      <label className="check"><input type="checkbox" checked={instr} onChange={e => setInstr(e.target.checked)} /> Instructions box</label>
      {content === "paper" && <label className="check"><input type="checkbox" checked={key} onChange={e => setKey(e.target.checked)} /> Answer key on the last page</label>}
      <div className="go">
        <button className="primary" onClick={go} disabled={busy}>Download {FMT[fmt]}</button>
        <a className="btn" href={`${base}/export/all.zip`}>Download all formats</a>
      </div>
      {msg && <p className="hint" role="status">{msg}</p>}
    </section>
  );
}
