const LABEL: Record<string, string> = {
  ok: "Verified", done: "Done", flagged: "Needs review", failed: "Failed", running: "Running", queued: "Queued",
  cancelled: "Cancelled", regenerating: "Regenerating", pending: "Pending",
};
export function tone(s: string) {
  if (s === "ok" || s === "done") return "good";
  if (s === "failed") return "bad";
  if (s === "flagged" || s === "cancelled") return "warn";
  if (s === "running" || s === "regenerating" || s === "queued") return "live";
  return "idle";
}
export default function Status({ s }: { s: string }) {
  return <span className={`status t-${tone(s)}`}>{LABEL[s] ?? s}</span>;
}
