"use client";
import { useEffect, useRef, useState } from "react";

type Ev = { t?: number; stage?: string; msg: string; level?: string; qno?: number };

export default function LiveLog({ jobId, onState }: { jobId: string; onState: (s: Record<string, unknown>) => void }) {
  const [lines, setLines] = useState<Ev[]>([]);
  const [follow, setFollow] = useState(true);
  const box = useRef<HTMLDivElement>(null);
  const cb = useRef(onState); cb.current = onState;

  useEffect(() => {
    setLines([]);
    const es = new EventSource(`/api/jobs/${jobId}/events`);
    es.addEventListener("log", e => { try { const ev = JSON.parse((e as MessageEvent).data); setLines(l => [...l, ev]); } catch {} });
    es.addEventListener("state", e => {
      const s = JSON.parse((e as MessageEvent).data); cb.current(s);
      if (!s.running && ["done", "failed", "cancelled"].includes(s.status)) setTimeout(() => es.close(), 5000);
    });
    return () => es.close();
  }, [jobId]);

  useEffect(() => { if (follow && box.current) box.current.scrollTop = box.current.scrollHeight; }, [lines, follow]);

  return (
    <div className="log-wrap">
      <div className="log-head">
        <h2>Activity</h2>
        <label className="check small"><input type="checkbox" checked={follow} onChange={e => setFollow(e.target.checked)} /> Follow</label>
      </div>
      <div className="log" ref={box} role="log" aria-live="polite">
        {!lines.length && <div className="log-empty">Waiting for the first event…</div>}
        {lines.map((l, i) => (
          <div key={i} className={`ll ${l.level ?? ""}`}>
            <span className="ls">{l.stage}</span>
            {l.qno !== undefined && <span className="lq">Q{l.qno}</span>}
            <span className="lm">{l.msg}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
