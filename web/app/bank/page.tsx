"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import MathHtml from "@/components/MathHtml";

type Fig = { path: string; width_pct?: number } | null;
type BankQ = {
  id: string; source: string; created: string; job_id?: string; job_qno?: number | string; section: string;
  chapter?: string; subtopic?: string; difficulty?: number | string; stem: string; options: string[]; answer?: string;
  solution?: string; passage?: string | null; figure?: Fig; option_figs?: string[] | null; used_in: string[];
};
type Tree = Record<string, Record<string, Record<string, number>>>;
type Resp = { total: number; items: BankQ[]; stats: { total: number; by_section: Record<string, number> }; tree: Tree };

const COLOR: Record<string, string> = { Physics: "var(--s-phy)", Chemistry: "var(--s-chem)",
  "English Proficiency": "var(--s-eng)", "Logical Reasoning": "var(--s-lr)", Mathematics: "var(--s-math)" };
const ORDER = ["Physics", "Chemistry", "English Proficiency", "Logical Reasoning", "Mathematics"];
const PAGE = 25;
const fig = (p?: string) => p ? `/api/bank/figs/${p.split("/").pop()}` : "";
const esc = (s?: string | null) => (s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "<br/>");
const sum = (o: Record<string, number>) => Object.values(o).reduce((a, b) => a + b, 0);
const byCount = <T,>(o: Record<string, T>, n: (v: T) => number) => Object.entries(o).sort((a, b) => n(b[1]) - n(a[1]) || a[0].localeCompare(b[0]));

type Sel = { section: string; chapter: string; subtopic: string };

export default function BankPage() {
  const [sel, setSel] = useState<Sel>({ section: "", chapter: "", subtopic: "" });
  const [q, setQ] = useState(""); const [diff, setDiff] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const [data, setData] = useState<Resp | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [live, setLive] = useState(true);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [added, setAdded] = useState(0);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Set<string>>(new Set());
  const seen = useRef<Set<string> | null>(null);
  const baseTotal = useRef<number | null>(null);

  const qs = new URLSearchParams({ ...sel, q, difficulty: diff, offset: "0", limit: String(limit) }).toString();
  useEffect(() => { seen.current = null; }, [sel, q, diff]);
  useEffect(() => {
    let stop = false;
    const load = () => api<Resp>(`/bank/list?${qs}`).then(d => {
      if (stop) return;
      if (baseTotal.current === null) baseTotal.current = d.stats.total;
      setAdded(d.stats.total - baseTotal.current);
      if (seen.current) {
        const nu = d.items.filter(i => !seen.current!.has(i.id)).map(i => i.id);
        if (nu.length) setFresh(s => new Set([...s, ...nu]));
      }
      seen.current = new Set([...(seen.current ?? []), ...d.items.map(i => i.id)]);
      setData(d); setErr(null);
    }).catch(e => setErr(String(e.message ?? e)));
    load();
    const t = live ? setInterval(load, 5000) : undefined;
    return () => { stop = true; if (t) clearInterval(t); };
  }, [qs, live]);

  const go = (s: Partial<Sel>) => {
    const n = { section: "", chapter: "", subtopic: "", ...s };
    setSel(n); setLimit(PAGE); window.scrollTo({ top: 0 });
    setExpanded(e => new Set([...e, n.section, `${n.section}/${n.chapter}`]));
  };
  const toggle = (k: string) => setExpanded(e => { const n = new Set(e); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const tree = data?.tree ?? {};
  const sections = [...ORDER.filter(s => tree[s]), ...Object.keys(tree).filter(s => !ORDER.includes(s))];
  const isOn = (s: string, c = "", t = "") => sel.section === s && sel.chapter === c && sel.subtopic === t;

  return (
    <div className="bk">
      <aside className="bk-side">
        <h3>Browse</h3>
        <ul className="bk-tree">
          <li><button className={`bk-node bk-sec ${isOn("") ? "on" : ""}`} onClick={() => go({})}>
            <span className="car" /><span className="lbl">All questions</span><span className="bk-n">{data?.stats.total ?? ""}</span></button></li>
          {sections.map(s => {
            const chs = tree[s]; const sOpen = expanded.has(s);
            return <li key={s}>
              <button className={`bk-node bk-sec ${isOn(s) ? "on" : ""}`} onClick={() => { go({ section: s }); }}>
                <span className="car" onClick={e => { e.stopPropagation(); toggle(s); }}>{sOpen ? "▾" : "▸"}</span>
                <span className="bk-dot" style={{ background: COLOR[s] ?? "var(--ink-3)" }} />
                <span className="lbl">{s}</span><span className="bk-n">{sum(Object.fromEntries(Object.entries(chs).map(([k, v]) => [k, sum(v)])))}</span>
              </button>
              {sOpen && <ul>{byCount(chs, sum).map(([c, subs]) => {
                const k = `${s}/${c}`; const cOpen = expanded.has(k);
                return <li key={c}>
                  <button className={`bk-node ${isOn(s, c) ? "on" : ""}`} onClick={() => go({ section: s, chapter: c })}>
                    <span className="car" onClick={e => { e.stopPropagation(); toggle(k); }}>{cOpen ? "▾" : "▸"}</span>
                    <span className="lbl">{c}</span><span className="bk-n">{sum(subs)}</span>
                  </button>
                  {cOpen && <ul>{byCount(subs, n => n).map(([t, n]) =>
                    <li key={t}><button className={`bk-node ${isOn(s, c, t) ? "on" : ""}`} onClick={() => go({ section: s, chapter: c, subtopic: t })}>
                      <span className="lbl">{t}</span><span className="bk-n">{n}</span></button></li>)}
                  </ul>}
                </li>;
              })}</ul>}
            </li>;
          })}
        </ul>
      </aside>

      <main>
        <p className="bk-crumb">
          <button onClick={() => go({})}>Question bank</button>
          {sel.section && <> / <button onClick={() => go({ section: sel.section })}>{sel.section}</button></>}
          {sel.chapter && <> / <button onClick={() => go({ section: sel.section, chapter: sel.chapter })}>{sel.chapter}</button></>}
          {sel.subtopic && <> / {sel.subtopic}</>}
        </p>
        <div className="bk-head">
          <h1 style={{ margin: 0 }}>{sel.subtopic || sel.chapter || sel.section || "All questions"}</h1>
          <label className="bk-live">
            <input type="checkbox" checked={live} onChange={e => setLive(e.target.checked)} />
            {live ? <><i /> Live</> : "Live off"}
            {added > 0 && <span className="bk-chip" style={{ background: "var(--good-soft)", color: "var(--good)" }}>+{added} new</span>}
          </label>
        </div>
        {!sel.section && data && <div style={{ display: "flex", height: 8, borderRadius: 4, overflow: "hidden", margin: "14px 0 0" }}>
          {sections.map(s => <div key={s} title={`${s}: ${data.stats.by_section[s]}`} style={{ flex: data.stats.by_section[s], background: COLOR[s] }} />)}
        </div>}

        <div className="bk-tools">
          <input placeholder="Search question text, subtopic or ID" value={q} onChange={e => { setQ(e.target.value); setLimit(PAGE); }} />
          <select value={diff} onChange={e => { setDiff(e.target.value); setLimit(PAGE); }}>
            <option value="">Any difficulty</option>
            {[1, 2, 3, 4, 5].map(d => <option key={d} value={d}>Difficulty {d}</option>)}
          </select>
        </div>
        {err && <p className="alert">{err}</p>}
        {data && <p className="dim" style={{ margin: "0 0 14px" }}>{data.total} question{data.total === 1 ? "" : "s"} · newest first</p>}
        {data && !data.items.length && <p className="empty">No questions match.</p>}

        {data?.items.map(it => {
          const shown = open.has(it.id);
          const d = Number(it.difficulty) || 0;
          const long = it.options.some(o => o.length > 60);
          return (
            <article key={it.id} className={`bk-card ${fresh.has(it.id) ? "fresh" : ""}`} style={{ borderTop: `3px solid ${COLOR[it.section] ?? "var(--line)"}` }}>
              <div className="bk-chead">
                <span className="bk-chip" style={{ color: COLOR[it.section] }}>{it.section}</span>
                <button className="bk-crumb" style={{ margin: 0 }} onClick={() => go({ section: it.section, chapter: it.chapter ?? "" })}>
                  <span style={{ color: "var(--ink-2)" }}>{it.chapter}</span></button>
                {it.subtopic && <><span className="dim">›</span>
                  <button className="bk-crumb" style={{ margin: 0 }} onClick={() => go({ section: it.section, chapter: it.chapter ?? "", subtopic: it.subtopic ?? "" })}>
                    <span style={{ color: "var(--ink-2)" }}>{it.subtopic}</span></button></>}
                <span title={`Difficulty ${d}`} style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                  <span className="bk-diff">{[1, 2, 3, 4, 5].map(i => <i key={i} className={i <= d ? "f" : ""} />)}</span><span className="dim">D{d || "?"}</span>
                </span>
                {it.source === "lr_generator" && <span className="bk-chip">LR generator</span>}
                {fresh.has(it.id) && <span className="bk-chip" style={{ background: "var(--good)", color: "#fff" }}>NEW</span>}
                <span className="dim" style={{ marginLeft: "auto" }}>{it.created?.replace("T", " ").slice(0, 16)}</span>
              </div>
              <div className="bk-body">
                {it.passage && <details className="bk-passage"><summary className="dim">Reading passage</summary><MathHtml html={esc(it.passage)} /></details>}
                <MathHtml html={esc(it.stem)} />
                {it.figure?.path && <img src={fig(it.figure.path)} alt="figure" style={{ display: "block", maxWidth: `${it.figure.width_pct ?? 60}%`, margin: "10px 0" }} />}
                <ol className={`bk-opts ${long ? "long" : ""}`}>
                  {it.options.map((o, i) => {
                    const L = "ABCD"[i];
                    return <li key={i} className={shown && L === it.answer ? "key" : ""}>
                      <span className="bub">{L}</span>
                      {it.option_figs?.[i] ? <img src={fig(it.option_figs[i])} alt={`option ${L}`} style={{ maxHeight: 90 }} /> : <MathHtml as="span" html={esc(o)} />}
                    </li>;
                  })}
                </ol>
              </div>
              {shown && it.solution && <div className="bk-sol"><h4>Answer {it.answer} · Solution</h4><MathHtml html={esc(it.solution)} /></div>}
              <div className="bk-foot">
                <button onClick={() => setOpen(s => { const n = new Set(s); if (n.has(it.id)) n.delete(it.id); else n.add(it.id); return n; })}>
                  {shown ? "Hide answer" : "Show answer & solution"}</button>
                {it.job_id && <Link href={`/jobs/${it.job_id}`} className="dim">From paper {it.job_id.slice(0, 8).replace(/(\d{4})(\d{2})(\d{2})/, "$3/$2/$1")} · Q{it.job_qno}</Link>}
                <span className="dim">{it.used_in.length ? `Reused in ${it.used_in.length} paper${it.used_in.length > 1 ? "s" : ""}` : "Not reused yet"}</span>
                <code>{it.id}</code>
              </div>
            </article>);
        })}
        {data && data.total > limit && <p style={{ textAlign: "center", marginTop: 20 }}>
          <button onClick={() => setLimit(l => l + PAGE)}>Show {Math.min(PAGE, data.total - limit)} more</button></p>}
      </main>
    </div>
  );
}
