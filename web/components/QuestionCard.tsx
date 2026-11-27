"use client";
import { useEffect, useRef, useState } from "react";
import { api, type Item } from "@/lib/api";
import MathHtml from "./MathHtml";
import Status from "./Status";

const L = ["A", "B", "C", "D"];

export default function QuestionCard({ jobId, item, onChange }: { jobId: string; item: Item; onChange: (it: Item) => void }) {
  const [instr, setInstr] = useState("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ stem: item.stem, options: item.options, answer: item.answer ?? "A", solution: item.solution ?? "" });
  const [err, setErr] = useState("");
  const poll = useRef<ReturnType<typeof setInterval> | null>(null);
  const it = item;
  const file = (p: string) => `/jobs/${jobId}/files/${p}`;

  useEffect(() => () => { if (poll.current) clearInterval(poll.current); }, []);
  useEffect(() => {
    if (it.status === "regenerating" && !poll.current) {
      poll.current = setInterval(async () => {
        const nu = await api<Item>(`/jobs/${jobId}/q/${it.qno}`);
        if (nu.status !== "regenerating") { clearInterval(poll.current!); poll.current = null; onChange(nu); }
      }, 4000);
    }
  }, [it.status, it.qno, jobId, onChange]);

  async function regen() {
    setErr("");
    try {
      await api(`/jobs/${jobId}/q/${it.qno}/regenerate`, { json: { instruction: instr } });
      onChange({ ...it, status: "regenerating" });
    } catch (e) { setErr((e as Error).message); }
  }
  async function save(body: object) {
    setErr("");
    try { onChange(await api<Item>(`/jobs/${jobId}/q/${it.qno}/edit`, { json: body })); setEditing(false); }
    catch (e) { setErr((e as Error).message); }
  }

  return (
    <article className={`qcard q-${it.status}`} id={`q${it.qno}`}>
      <header className="qhead">
        <span className="qno">{it.qno}</span>
        <div className="qtopic">
          <b>{it.slot.chapter}</b>{it.slot.subtopic && <span>{it.slot.subtopic}</span>}
        </div>
        <div className="qtags">
          <span className="tag">{it.section}</span>
          {it.difficulty !== undefined && <span className="tag" title="Difficulty, 1–5">Level {it.difficulty}</span>}
          {it.slot.lr_generator && <span className="tag">{it.slot.lr_generator}</span>}
          <Status s={it.status} />
        </div>
      </header>

      {!editing ? (
        <div className="paper">
          <MathHtml html={it.stem_html} />
          {it.figure && <figure><img src={file(it.figure.path)} alt="" style={{ width: Math.min(it.figure.width_pct * 4, 520) }} /></figure>}
          <ol className="opts">
            {it.options_html.map((o, i) => (
              <li key={i} className={L[i] === it.answer ? "key" : ""}>
                <span className="bub" aria-label={L[i] === it.answer ? `${L[i]}, correct` : L[i]}>{L[i]}</span>
                <div>{it.option_figs?.[i] && <img src={file(it.option_figs[i])} alt="" width={110} />}<MathHtml html={o} /></div>
              </li>
            ))}
          </ol>
          {it.solution_html && (
            <details className="sol"><summary>Solution</summary><MathHtml html={it.solution_html} /></details>
          )}
        </div>
      ) : (
        <div className="editor">
          <div className="field"><label>Question</label><textarea rows={5} value={draft.stem} onChange={e => setDraft({ ...draft, stem: e.target.value })} /></div>
          <div className="two">
            {draft.options.map((o, i) => (
              <div className="field" key={i}><label>Option {L[i]}</label>
                <input value={o} onChange={e => setDraft({ ...draft, options: draft.options.map((x, j) => j === i ? e.target.value : x) })} /></div>
            ))}
          </div>
          <div className="field"><label>Correct option</label>
            <div className="seg">{L.map(x => <button key={x} type="button" aria-pressed={draft.answer === x} onClick={() => setDraft({ ...draft, answer: x })}>{x}</button>)}</div></div>
          <div className="field"><label>Solution</label><textarea rows={4} value={draft.solution} onChange={e => setDraft({ ...draft, solution: e.target.value })} /></div>
          <div className="go"><button className="primary" onClick={() => save(draft)}>Save changes</button><button onClick={() => setEditing(false)}>Discard</button></div>
        </div>
      )}

      {(it.notes?.length || it.verdicts?.length) ? (
        <div className="checks">
          {it.notes?.length ? <p className="note">{it.notes.join(" · ")}</p> : null}
          {it.verdicts?.length ? (
            <p className="verd">Checked by {it.verdicts.map((v, i) => (
              <span key={i}>{i > 0 && ", "}{(v.model ?? v.stage).split("/").pop()} <b className={v.answer === it.answer ? "agree" : "disagree"}>{v.answer ?? "no answer"}</b>{v.issues?.length ? ` (${v.issues.join("; ")})` : ""}</span>
            ))}</p>
          ) : null}
        </div>
      ) : null}

      {!editing && (
        <footer className="qactions">
          <input value={instr} onChange={e => setInstr(e.target.value)} placeholder="What to change, e.g. make it numerical" aria-label="Instruction for rewrite" />
          <button onClick={regen} disabled={it.status === "regenerating"}>{it.status === "regenerating" ? "Rewriting…" : "Rewrite"}</button>
          <button onClick={() => { setDraft({ stem: it.stem, options: it.options, answer: it.answer ?? "A", solution: it.solution ?? "" }); setEditing(true); }}>Edit</button>
          {it.status !== "ok" && <button className="ok" onClick={() => save({ mark_ok: true })}>Mark verified</button>}
        </footer>
      )}
      {err && <p className="alert">{err}</p>}
    </article>
  );
}
