"use client";
import { useMemo, useState } from "react";
import { useApi, type JobState } from "@/lib/api";
import JobList from "@/components/JobList";

const FILTERS = [["all", "All"], ["running", "Running"], ["done", "Done"], ["other", "Stopped / failed"]];

export default function PapersPage() {
  const { data, error } = useApi<{ jobs: JobState[] }>("/jobs");
  const [q, setQ] = useState("");
  const [st, setSt] = useState("all");
  const jobs = useMemo(() => (data?.jobs ?? []).filter(j => {
    const s = String(j.status);
    if (st === "running" && s !== "running") return false;
    if (st === "done" && s !== "done") return false;
    if (st === "other" && (s === "running" || s === "done")) return false;
    return !q || j.config.title.toLowerCase().includes(q.toLowerCase()) || j.id.includes(q);
  }), [data, q, st]);

  return (
    <div style={{ maxWidth: 760, margin: "0 auto", padding: "40px 24px" }}>
      <h1>Generated papers</h1>
      {error && <p className="err">{String(error)}</p>}
      <div style={{ display: "flex", gap: 12, margin: "16px 0" }}>
        <input placeholder="Search by title" value={q} onChange={e => setQ(e.target.value)} style={{ flex: 1 }} />
        <select value={st} onChange={e => setSt(e.target.value)}>
          {FILTERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </div>
      {data && <p className="footnote">{jobs.length} of {data.jobs.length} papers</p>}
      {data && !jobs.length && <p className="empty">No papers match.</p>}
      <JobList jobs={jobs} />
    </div>
  );
}
