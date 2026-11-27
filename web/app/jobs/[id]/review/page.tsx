"use client";
import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { useApi, type Item, type JobState } from "@/lib/api";
import QuestionCard from "@/components/QuestionCard";

type JobResp = { job: JobState; items: Item[]; sections: string[] };

export default function Review({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error, setData } = useApi<JobResp>(`/jobs/${id}`);
  const [section, setSection] = useState("");
  const [status, setStatus] = useState("");

  const onChange = useCallback((nu: Item) =>
    setData(d => d ? { ...d, items: d.items.map(i => i.qno === nu.qno ? nu : i) } : d), [setData]);

  useEffect(() => {
    if (data && location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView();
  }, [data]);

  if (error) return <p className="alert">{error}</p>;
  if (!data) return <p className="loading">Loading…</p>;
  const all = data.items;
  const shown = all.filter(i => (!section || i.section === section) &&
    (!status || (status === "flagged" ? i.status !== "ok" : i.status === status)));
  const ok = all.filter(i => i.status === "ok").length;

  return (
    <div className="review">
      <header className="job-head">
        <div>
          <Link href={`/jobs/${id}`} className="back">{data.job.config.title}</Link>
          <h1>Review questions</h1>
          <p className="meta">{ok} of {all.length} verified. Rewrite a question with an instruction, edit it by hand, or mark it verified.</p>
        </div>
        <div className="job-actions">
          <a className="btn" target="_blank" href={`/jobs/${id}/view/paper.html`}>Open paper preview</a>
          <Link className="btn primary" href={`/jobs/${id}#export`}>Export</Link>
        </div>
      </header>
      <div className="filters">
        <div className="seg" aria-label="Section">
          <button aria-pressed={!section} onClick={() => setSection("")}>All sections</button>
          {data.sections.map(s => <button key={s} aria-pressed={s === section} onClick={() => setSection(s)}>{s}</button>)}
        </div>
        <div className="seg" aria-label="Status">
          {[["", "Any status"], ["flagged", `Needs review (${all.length - ok})`], ["ok", "Verified"]].map(([v, l]) =>
            <button key={v} aria-pressed={status === v} onClick={() => setStatus(v)}>{l}</button>)}
        </div>
      </div>
      {shown.map(it => <QuestionCard key={it.qno} jobId={id} item={it} onChange={onChange} />)}
      {!shown.length && <p className="empty">No questions match these filters.</p>}
    </div>
  );
}
