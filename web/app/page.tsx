"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, useApi, type JobState } from "@/lib/api";
import JobList from "@/components/JobList";

type Pattern = { id: string; title: string; sections: [string, number][]; total: number };
type Corpus = { id: string; n: number; pending?: boolean };
type Home = { patterns: Pattern[]; profiles: string[]; active: string; jobs: JobState[]; corpus: Corpus[]; bank?: Record<string, number> };

const SOURCES = [["new", "Write new questions"], ["direct", "Pick from question bank"],
  ["variant", "New questions based on bank ones"], ["mixed", "Mixed"]];
const DIFF = [["easier", "Easier"], ["match", "Like past papers"], ["harder", "Harder"], ["much_harder", "Much harder"]];

export default function HomePage() {
  const { data, error } = useApi<Home>("/home");
  const router = useRouter();
  const [f, setF] = useState({ title: "BITSAT Practice Paper", subtitle: "", pattern_id: "", profile: "",
    difficulty: "match", seed: "", run_critic: true, check_figures: true, add_to_bank: true, source: "new" });
  const [mix, setMix] = useState({ direct: 30, variant: 40, new: 30 });
  const mixTotal = mix.direct + mix.variant + mix.new;
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
      const body = { ...f, mix: f.source === "mixed" ? mix : null, counts: mode === "custom" ? Object.fromEntries(sections.filter(([, c]) => c > 0)) : null };
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
          <div className="field"><label htmlFor="src">Question source</label>
            <select id="src" value={f.source} onChange={set("source")}>{SOURCES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
            {f.source !== "new" && <span className="hint">
              Bank: {data?.bank && Object.keys(data.bank).length
                ? Object.entries(data.bank).map(([s, n]) => `${s} ${n}`).join(" · ")
                : "empty"}. Slots with no matching bank question (same chapter, difficulty ±1) are written new.
            </span>}
          </div>
          {f.source === "mixed" && (
            <div className="two">
              {(["direct", "variant", "new"] as const).map(k => (
                <div className="field" key={k}><label htmlFor={`mix-${k}`}>{k === "direct" ? "% from bank" : k === "variant" ? "% bank variants" : "% new"}</label>
                  <input id={`mix-${k}`} type="number" min={0} max={100} value={mix[k]}
                    onChange={e => setMix({ ...mix, [k]: Math.max(0, Math.min(100, Number(e.target.value) || 0)) })} /></div>
              ))}
              {mixTotal !== 100 && <p className="alert">Percentages add up to {mixTotal}; they must add up to 100.</p>}
            </div>
          )}
          <details className="more">
            <summary>More options</summary>
            <div className="field"><label htmlFor="seed">Seed</label><input id="seed" value={f.seed} onChange={set("seed")} placeholder="Random" inputMode="numeric" /></div>
            <label className="check"><input type="checkbox" checked={f.run_critic} onChange={set("run_critic")} /> Critic review, then rewrite weak questions</label>
            <label className="check"><input type="checkbox" checked={f.check_figures} onChange={set("check_figures")} /> Check generated figures visually</label>
            <label className="check"><input type="checkbox" checked={f.add_to_bank} onChange={set("add_to_bank")} /> Add verified questions to the question bank</label>
          </details>
          {err && <p className="alert">{err}</p>}
          <div className="go">
            <button className="primary" disabled={busy || !total || (f.source === "mixed" && mixTotal !== 100)}>{busy ? "Starting…" : `Generate ${total} questions`}</button>
            <span className="hint">{total >= 100 ? "A full paper takes 15–30 min and costs about $5–8 on balanced." : "Small runs finish in a few minutes."}</span>
          </div>
        </form>
      </section>

      <section className="runs">
        <h2>Recent papers</h2>
        {data && !data.jobs.length && <p className="empty">Nothing generated yet. Start with a short run of 3 questions per section to check the output.</p>}
        <JobList jobs={(data?.jobs ?? []).slice(0, 5)} />
        {data && data.jobs.length > 5 && <p className="footnote"><Link href="/papers">View all {data.jobs.length} papers →</Link></p>}
        {data && <p className="footnote">Style, topic weights and examples come from {corpusQs.toLocaleString()} questions in {corpusPapers} <Link href="/corpus">past papers</Link>.</p>}
      </section>
    </div>
  );
}
