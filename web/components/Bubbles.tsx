import type { Mark } from "@/lib/api";
import { tone } from "./Status";

/** OMR-style answer-sheet grid: one bubble per question, grouped by section. */
export default function Bubbles({ marks, total, size = "lg", href }:
  { marks: Mark[]; total?: number; size?: "lg" | "sm"; href?: (q: number) => string }) {
  const byQ = new Map(marks.map(m => [m.qno, m]));
  const n = Math.max(total ?? 0, marks.length, ...marks.map(m => m.qno));
  const groups: { section: string; qs: number[] }[] = [];
  for (let q = 1; q <= n; q++) {
    const last = groups[groups.length - 1];
    const known = byQ.get(q)?.section;
    // Unwritten questions join the section before them; only a trailing run gets its own group.
    const sec = known ?? (marks.some(m => m.qno > q) && last ? last.section : "Not started yet");
    if (last && last.section === sec) last.qs.push(q); else groups.push({ section: sec, qs: [q] });
  }
  return (
    <div className={`omr omr-${size}`}>
      {groups.map((g, gi) => {
        const ok = g.qs.filter(q => byQ.get(q)?.status === "ok").length;
        return (
          <div className="omr-group" key={gi}>
            {size === "lg" && <div className="omr-label">{g.section}
              {byQ.has(g.qs[0]) || g.qs.some(q => byQ.has(q)) ? <small>{ok}/{g.qs.length}</small> : <small>Q{g.qs[0]}–{g.qs[g.qs.length - 1]}</small>}</div>}
            <div className="omr-row">
              {g.qs.map(q => {
                const m = byQ.get(q); const t = m ? tone(m.status) : "empty";
                const title = `Q${q}${m ? `: ${m.status}` : ": not written yet"}`;
                const inner = size === "lg" ? <span>{q}</span> : null;
                return href && m
                  ? <a key={q} href={href(q)} className={`b b-${t}`} title={title} aria-label={title}>{inner}</a>
                  : <span key={q} className={`b b-${t}`} title={title}>{inner}</span>;
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function Legend({ marks, total }: { marks: Mark[]; total?: number }) {
  const c = (f: (s: string) => boolean) => marks.filter(m => f(m.status)).length;
  const rows: [string, string, number][] = [
    ["good", "Verified", c(s => s === "ok")],
    ["warn", "Needs review", c(s => s === "flagged")],
    ["bad", "Failed", c(s => s === "failed")],
    ["live", "In progress", c(s => tone(s) === "live" || s === "pending")],
    ["empty", "Not written", Math.max(0, (total ?? 0) - marks.length)],
  ];
  return (
    <ul className="legend omr">
      {rows.filter(([, , n]) => n > 0).map(([t, l, n]) => <li key={t}><span className={`b b-${t}`} />{l} <b>{n}</b></li>)}
    </ul>
  );
}
