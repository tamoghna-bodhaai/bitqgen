import Link from "next/link";
import { money, type JobState } from "@/lib/api";
import Status from "@/components/Status";
import Bubbles from "@/components/Bubbles";

const clock = (t?: number) => t ? new Date(t * 1000).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";
function dur(s: number) {
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m ${x}s` : `${x}s`;
}

export default function JobList({ jobs }: { jobs: JobState[] }) {
  return (
    <ul className="joblist">
      {jobs.map(j => (
        <li key={j.id}>
          <Link href={`/jobs/${j.id}`} className="jobrow">
            <div className="jr-top">
              <span className="jr-title">{j.config.title}</span>
              <Status s={j.status} />
            </div>
            <Bubbles marks={j.marks ?? []} total={j.progress.total} size="sm" />
            <div className="jr-meta">
              <span>{j.progress.ok ?? 0} of {j.progress.total ?? 0} verified</span>
              <span>{money(j.cost)}</span>
            </div>
            <div className="jr-meta jr-time">
              <span>Start {clock(j.started ?? j.created)}</span>
              <span>End {j.finished ? clock(j.finished) : j.running || j.status === "running" ? "in progress" : "—"}</span>
              <span className="jr-dur">⏱ {(() => { const s = j.started ?? j.created; if (!s) return "—";
                const e = j.finished ?? (j.running || j.status === "running" ? Date.now() / 1000 : undefined);
                return e ? dur(e - s) + (j.finished ? "" : " so far") : "—"; })()}</span>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}
