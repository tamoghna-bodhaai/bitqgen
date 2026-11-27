// Pass the FastAPI SSE stream through untouched (the generic rewrite proxy gzips and buffers it).
const API = process.env.BITQGEN_API ?? "http://127.0.0.1:8000";
export const dynamic = "force-dynamic";

export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const since = new URL(req.url).searchParams.get("since") ?? "0";
  const up = await fetch(`${API}/api/jobs/${encodeURIComponent(id)}/events?since=${since}`, {
    headers: { Accept: "text/event-stream", "Accept-Encoding": "identity" }, signal: req.signal, cache: "no-store",
  });
  return new Response(up.body, {
    status: up.status,
    headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no" },
  });
}
