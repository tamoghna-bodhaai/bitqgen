"use client";
import { FormEvent, useEffect, useRef, useState } from "react";
import { api, money, useApi } from "@/lib/api";

type Ingest = {
  status: string; error?: string | null; running?: boolean; source?: string; questions?: number; merged?: number;
  progress?: { done: number; total: number }; cost?: number; problems?: string[];
};
type C = { id: string; n: number; title?: string; figs?: number; flagged?: number; pending?: boolean; pages?: number; ingest?: Ingest };

const STAGE: Record<string, string> = {
  queued: "Queued", layout: "Reading layout", transcribing: "Transcribing", merging: "Merging",
  rebuilding: "Updating topic weights", done: "Added", error: "Failed",
};
const active = (i?: Ingest) => !!i && i.status !== "done" && i.status !== "error" && i.running !== false;

function Upload({ onDone }: { onDone: () => void }) {
  const file = useRef<HTMLInputElement>(null);
  const [id, setId] = useState("");
  const [overwrite, setOverwrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const f = file.current?.files?.[0];
    if (!f) return setErr("Choose a PDF first.");
    const fd = new FormData();
    fd.append("file", f);
    fd.append("id", id);
    fd.append("overwrite", String(overwrite));
    setBusy(true); setErr(null);
    try {
      const r = await fetch("/api/corpus/upload", { method: "POST", body: fd });
      if (!r.ok) { let m = await r.text(); try { m = JSON.parse(m).detail ?? m; } catch {} throw new Error(m); }
      if (file.current) file.current.value = "";
      setId(""); setOverwrite(false); onDone();
    } catch (e) { setErr(String((e as Error).message ?? e)); }
    finally { setBusy(false); }
  }

  return (
    <form onSubmit={submit} className="form" style={{ maxWidth: 640, marginBottom: 28 }}>
      <h2>Add a past paper</h2>
      <p className="hint" style={{ marginTop: 0 }}>Upload a BITSAT solved paper PDF in the eSaral layout. The answer key and figures are read from the PDF, and a vision model (stage <code>transcriber</code>, about $0.30–1 per paper) transcribes the text. When it finishes, topic weights and style profiles are rebuilt, which replaces any hand edits to the syllabus.</p>
      <div className="two">
        <div className="field"><label htmlFor="pdf">PDF</label><input id="pdf" ref={file} type="file" accept="application/pdf,.pdf" /></div>
        <div className="field"><label htmlFor="pid">Paper id</label><input id="pid" value={id} onChange={e => setId(e.target.value)} placeholder="From file name, e.g. 2027s1" /></div>
      </div>
      <label className="check small"><input type="checkbox" checked={overwrite} onChange={e => setOverwrite(e.target.checked)} /> Replace an existing paper with this id</label>
      {err && <p className="alert">{err}</p>}
      <div className="go"><button className="primary" disabled={busy}>{busy ? "Uploading…" : "Upload and extract"}</button></div>
    </form>
  );
}

function IngestCell({ p, onRetry }: { p: C; onRetry: () => void }) {
  const i = p.ingest!;
  const stalled = i.status !== "done" && i.status !== "error" && i.running === false;
  const cls = i.status === "error" || stalled ? "t-bad" : i.status === "done" ? "t-good" : "t-live";
  const prog = i.status === "transcribing" && i.progress?.total ? ` ${i.progress.done}/${i.progress.total} columns` : "";
  return <>
    <span className={`status ${cls}`}>{stalled ? "Stopped" : STAGE[i.status] ?? i.status}{prog}</span>
    {" "}<span className="dim">{money(i.cost)}</span>
    {i.error && <div className="dim">{i.error}</div>}
    {(i.status === "error" || stalled) && <button type="button" onClick={onRetry} style={{ marginLeft: 8 }}>Retry</button>}
  </>;
}

export default function Corpus() {
  const { data, error, reload } = useApi<C[]>("/corpus");
  const busy = data?.some(p => active(p.ingest));
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(reload, 3000);
    return () => clearInterval(t);
  }, [busy, reload]);
  const retry = (id: string) => api(`/corpus/${id}/ingest/retry`, { method: "POST" }).then(reload).catch(e => alertLike(e));
  const [msg, setMsg] = useState<string | null>(null);
  const alertLike = (e: unknown) => setMsg(String((e as Error).message ?? e));

  return (
    <div className="page">
      <h1>Past papers</h1>
      <p className="lede">BITSAT papers extracted from <code>bitsat/</code> or uploaded here. They set the topic weights, the writing style and the examples each author sees.</p>
      <Upload onDone={reload} />
      {error && <p className="alert">{error}</p>}
      {msg && <p className="alert">{msg}</p>}
      <div className="tablewrap"><table className="t">
        <thead><tr><th>Paper</th><th className="r">Questions</th><th className="r">With figures</th><th className="r">Flagged in source</th><th>Open</th></tr></thead>
        <tbody>{data?.map(p => (
          <tr key={p.id}>
            <td><b>{p.id}</b>{p.ingest?.source && <div className="dim">{p.ingest.source}</div>}</td>
            {p.pending ? <>
              <td colSpan={3}>{p.ingest ? <IngestCell p={p} onRetry={() => retry(p.id)} />
                : <span className="dim">Not extracted yet, {p.pages} page images ready</span>}</td><td /></> : <>
              <td className="r num">{p.n}{p.ingest?.problems?.length ? <div className="dim">{p.ingest.problems.length} merge warning(s)</div> : null}</td>
              <td className="r num">{p.figs}</td><td className="r num">{p.flagged}</td>
              <td className="links">
                {p.ingest && p.ingest.status !== "done" && <IngestCell p={p} onRetry={() => retry(p.id)} />}
                <a target="_blank" href={`/corpus/${p.id}/view/paper.html`}>Paper</a>
                <a target="_blank" href={`/corpus/${p.id}/view/solutions.html`}>With solutions</a>
                <a href={`/corpus/${p.id}/export?content=solutions&fmt=pdf`}>PDF</a>
                <a href={`/corpus/${p.id}/export?content=solutions&fmt=docx`}>Word</a>
              </td></>}
          </tr>))}</tbody>
      </table></div>
    </div>
  );
}
