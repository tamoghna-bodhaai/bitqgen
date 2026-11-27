"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, money, useApi, type JobState } from "@/lib/api";
import Status from "@/components/Status";
import Bubbles from "@/components/Bubbles";

type Pattern = { id: string; title: string; sections: [string, number][]; total: number };
type Corpus = { id: string; n: number; pending?: boolean };
type Home = { patterns: Pattern[]; profiles: string[]; active: string; jobs: JobState[]; corpus: Corpus[] };

const DIFF = [["easier", "Easier"], ["match", "Like past papers"], ["harder", "Harder"], ["much_harder", "Much harder"]];

export default function HomePage() {
  const { data, error } = useApi<Home>("/home");
  const router = useRouter();
  const [f, setF] = useState({ title: "BITSAT Practice Paper", subtitle: "", pattern_id: "", profile: "",
    difficulty: "match", seed: "", run_critic: true, check_figures: true });
  const [mode, setMode] = useState<"full" | "custom">("full");
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const pattern = useMemo(() => data?.patterns.find(p => p.id === f.pattern_id) ?? data?.patterns[0], [data, f.pattern_id]);
  useEffect(() => {
    if (!data) return;
    setF(x => ({ ...x, pattern_id: x.pattern_id || data.patterns[0]?.id || "", profile: x.profile || data.active }));
  }, [data]);
  useEffect(() => {
    if (pattern) setCounts(Object.fromEntries(pattern.sections.map(([n]) => [n, 3])));
  }, [pattern]);

  const sections = mode === "full" ? pattern?.sections ?? [] : (pattern?.sections ?? []).map(([n]) => [n, counts[n] ?? 0] as [string, number]);
  const total = sections.reduce((a, [, c]) => a + c, 0);

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null);
    try {
      const body = { ...f, counts: mode === "custom" ? Object.fromEntries(sections.filter(([, c]) => c > 0)) : null };
      const { id } = await api<{ id: string }>("/jobs", { json: body });
      router.push(`/jobs/${id}`);
    } catch (e) { setErr(String((e as Error).message)); setBusy(false); }
  }

  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.type === "checkbox" ? (e.target as HTMLInputElement).checked : e.target.value });

  const corpusQs = data?.corpus.reduce((a, c) => a + (c.n || 0), 0) ?? 0;
  const corpusPapers = data?.corpus.filter(c => c.n).length ?? 0;

  return (
    <div className="home">
      <section className="compose">
        <h1>New paper</h1>
        <p className="lede">Write an original BITSAT paper in the pattern, section order and difficulty of the past papers, with verified answers and worked solutions.</p>
        {error && <p className="alert">Can’t reach the studio API: {error}. Start it with <code>uv run uvicorn app.main:app --port 8000</code>.</p>}
        <form onSubmit={submit} className="form">
          <div className="field"><label htmlFor="t">Title</label><input id="t" value={f.title} onChange={set("title")} /></div>
          <div className="field"><label htmlFor="st">Subtitle</label><input id="st" value={f.subtitle} onChange={set("subtitle")} placeholder="Mock test 3" /></div>

          <fieldset className="field">
            <legend>Questions</legend>
            <div className="seg" role="radiogroup">
              <button type="button" aria-pressed={mode === "full"} onClick={() => setMode("full")}>Full paper</button>
              <button type="button" aria-pressed={mode === "custom"} onClick={() => setMode("custom")}>Choose counts</button>
            </div>
            <div className="secbar" aria-hidden>
              {sections.map(([n, c]) => c > 0 && <span key={n} style={{ flexGrow: c }} className={`sb sb-${n.split(" ")[0].toLowerCase()}`} />)}
            </div>
            <ul className="seclist">
              {sections.map(([n, c]) => (
                <li key={n}>
                  <span className={`dot sb-${n.split(" ")[0].toLowerCase()}`} />
                  <span className="sname">{n}</span>
                  {mode === "full" ? <span className="num">{c}</span> :
                    <input type="number" min={0} max={60} aria-label={`${n} questions`} value={c}
                      onChange={e => setCounts({ ...counts, [n]: Math.max(0, +e.target.value || 0) })} />}
                </li>
              ))}
              <li className="total"><span /><span className="sname">Total</span><span className="num">{total}</span></li>
            </ul>
          </fieldset>

          <div className="two">
            <div className="field"><label htmlFor="d">Difficulty</label>
              <select id="d" value={f.difficulty} onChange={set("difficulty")}>{DIFF.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
            <div className="field"><label htmlFor="p">Model profile</label>
              <select id="p" value={f.profile} onChange={set("profile")}>{data?.profiles.map(p => <option key={p}>{p}</option>)}</select></div>
          </div>
          {(data?.patterns.length ?? 0) > 1 && (
            <div className="field"><label htmlFor="pat">Pattern</label>
              <select id="pat" value={f.pattern_id} onChange={set("pattern_id")}>{data!.patterns.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}</select></div>
          )}
          <details className="more">
            <summary>More options</summary>
            <div className="field"><label htmlFor="seed">Seed</label><input id="seed" value={f.seed} onChange={set("seed")} placeholder="Random" inputMode="numeric" /></div>
            <label className="check"><input type="checkbox" checked={f.run_critic} onChange={set("run_critic")} /> Critic review, then rewrite weak questions</label>
            <label className="check"><input type="checkbox" checked={f.check_figures} onChange={set("check_figures")} /> Check generated figures visually</label>
          </details>
          {err && <p className="alert">{err}</p>}
          <div className="go">
            <button className="primary" disabled={busy || !total}>{busy ? "Starting…" : `Generate ${total} questions`}</button>
            <span className="hint">{total >= 100 ? "A full paper takes 15–30 min and costs about $5–8 on balanced." : "Small runs finish in a few minutes."}</span>
          </div>
        </form>
      </section>

      <section className="runs">
        <h2>Recent papers</h2>
        {data && !data.jobs.length && <p className="empty">Nothing generated yet. Start with a short run of 3 questions per section to check the output.</p>}
        <ul className="joblist">
          {data?.jobs.map(j => (
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
                  <span>{j.id.slice(0, 8).replace(/(\d{4})(\d{2})(\d{2})/, "$3/$2/$1")}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
        {data && <p className="footnote">Style, topic weights and examples come from {corpusQs.toLocaleString()} questions in {corpusPapers} <Link href="/corpus">past papers</Link>.</p>}
      </section>
    </div>
  );
}
