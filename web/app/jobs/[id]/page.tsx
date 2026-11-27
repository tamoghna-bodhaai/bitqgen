"use client";
import Link from "next/link";
import { use, useCallback, useRef } from "react";
import { api, money, useApi, type Item, type JobState } from "@/lib/api";
import Status from "@/components/Status";
import Bubbles, { Legend } from "@/components/Bubbles";
import LiveLog from "@/components/LiveLog";
import ExportPanel from "@/components/ExportPanel";

type JobResp = { job: JobState; items: Item[]; sections: string[]; has_paper: boolean };

const STAGES: [string, string[]][] = [
  ["Plan", ["queued", "planning"]], ["Write and verify", ["generating"]], ["Critic", ["critic"]],
  ["Rewrite", ["revising"]], ["Solutions", ["solutions"]], ["Export", ["exporting"]],
];

export default function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error, reload, setData } = useApi<JobResp>(`/jobs/${id}`);
  const lastDone = useRef(-1);

  const onState = useCallback((s: Record<string, unknown>) => {
    const p = (s.progress ?? {}) as JobState["progress"];
    setData(d => d ? { ...d, job: { ...d.job, ...(s as Partial<JobState>), progress: { ...d.job.progress, ...p } } } : d);
    const key = (p.done ?? 0) * 1000 + (p.ok ?? 0);
    if (key !== lastDone.current) { lastDone.current = key; reload(); }
  }, [reload, setData]);

  if (error) return <p className="alert">{error}</p>;
  if (!data) return <p className="loading">Loading…</p>;
  const { job, items, sections } = data;
  const p = job.progress;
  const marks = items.map(i => ({ qno: i.qno, status: i.status, section: i.section }));
  const terminal = ["done", "failed", "cancelled"].includes(job.status);
  const idx = job.status === "done" ? STAGES.length : STAGES.findIndex(([, ks]) => ks.includes(job.stage));
  // A stopped job reports stage "cancelled"/"failed": infer where it stopped from progress.
  const shownIdx = idx >= 0 ? idx : terminal ? ((p.done ?? 0) < (p.total ?? 0) ? 1 : 2) : 0;
  const c = job.config;

  async function act(a: "cancel" | "resume") { await api(`/jobs/${id}/${a}`, { method: "POST" }); reload(); }

  return (
    <div className="job">
      <header className="job-head">
        <div>
          <Link href="/" className="back">All papers</Link>
          <h1>{c.title}{c.subtitle && <span className="subt"> {c.subtitle}</span>}</h1>
          <p className="meta">
            {c.counts ? "Custom counts" : "Full pattern"}, difficulty {c.difficulty.replace("_", " ")}, {c.profile || "default"} profile, seed {c.seed}
          </p>
        </div>
        <div className="job-actions">
          <Status s={job.running ? "running" : job.status} />
          {job.running && <button className="danger" onClick={() => act("cancel")}>Stop</button>}
          {!job.running && (job.status === "failed" || job.status === "cancelled") && <button className="primary" onClick={() => act("resume")}>Resume</button>}
        </div>
      </header>

      {job.error && <p className="alert">{job.error}</p>}

      <section className="sheet">
        <div className="sheet-stats">
          <div><b>{p.done ?? 0}<small>/{p.total ?? 0}</small></b><span>written</span></div>
          <div className="good"><b>{p.ok ?? 0}</b><span>verified</span></div>
          <div className="warn"><b>{p.flagged ?? 0}</b><span>need review</span></div>
          <div><b>{money(job.cost)}</b><span>spent</span></div>
        </div>
        <Legend marks={marks} total={p.total} />
        <Bubbles marks={marks} total={p.total} href={q => `/jobs/${id}/review#q${q}`} />
        <ol className="rail">
          {STAGES.map(([l], i) => (
            <li key={l} className={i < shownIdx ? "past" : i === shownIdx ? (terminal ? "stopped" : "now") : ""}>{l}</li>
          ))}
        </ol>
        <div className="sheet-links">
          <Link className="btn primary" href={`/jobs/${id}/review`}>Review questions</Link>
          <a className="btn" target="_blank" href={`/jobs/${id}/view/paper.html`}>Open paper preview</a>
          <a className="btn" target="_blank" href={`/jobs/${id}/view/solutions.html`}>Open solutions preview</a>
        </div>
      </section>

      <div className="job-grid">
        <LiveLog jobId={id} onState={onState} />
        {sections.length > 0 ? <ExportPanel base={`/jobs/${id}`} sections={sections} />
          : <section className="export"><h2>Export</h2><p className="empty">Export opens once the first questions are written.</p></section>}
      </div>

      <section>
        <h2>Questions</h2>
        <div className="tablewrap">
          <table className="t">
            <thead><tr><th>Q</th><th>Section</th><th>Topic</th><th>Difficulty</th><th>Status</th><th>Attempts</th><th>Notes</th></tr></thead>
            <tbody>
              {items.map(i => (
                <tr key={i.qno}>
                  <td><Link href={`/jobs/${id}/review#q${i.qno}`}>{i.qno}</Link></td>
                  <td>{i.section}</td>
                  <td>{i.slot.chapter}<div className="dim">{i.slot.subtopic}</div></td>
                  <td>{i.difficulty ?? ""}</td>
                  <td><Status s={i.status} /></td>
                  <td>{i.attempts ?? ""}</td>
                  <td className="dim">{(i.notes ?? []).join("; ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
