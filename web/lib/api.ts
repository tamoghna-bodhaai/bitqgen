"use client";
import { useCallback, useEffect, useState } from "react";

export type Mark = { qno: number; status: string; section: string };
export type Progress = { total?: number; done?: number; ok?: number; flagged?: number };
export type JobState = {
  id: string; status: string; stage: string; progress: Progress; cost?: number; error?: string;
  running?: boolean; created?: number; started?: number; finished?: number; marks?: Mark[];
  config: { title: string; subtitle?: string; pattern_id: string; counts?: Record<string, number> | null;
            profile?: string | null; difficulty: string; seed?: number };
};
export type Verdict = { stage: string; model?: string; answer?: string; issues?: string[] };
export type Item = {
  qno: number; section: string; status: string; difficulty?: number; attempts?: number; notes?: string[];
  slot: { chapter?: string; subtopic?: string; lr_generator?: string | null };
  stem: string; options: string[]; answer?: string; solution?: string;
  stem_html: string; options_html: string[]; solution_html: string;
  figure?: { path: string; width_pct: number } | null; option_figs?: string[] | null; verdicts?: Verdict[];
};

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const r = await fetch(`/api${path}`, {
    ...rest,
    ...(json !== undefined ? { method: rest.method ?? "POST", headers: { "Content-Type": "application/json" },
                              body: JSON.stringify(json) } : {}),
  });
  if (!r.ok) {
    let msg = await r.text();
    try { msg = JSON.parse(msg).detail ?? msg; } catch {}
    throw new Error(msg || `Request failed (${r.status})`);
  }
  return r.json();
}

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    if (!path) return;
    api<T>(path).then(d => { setData(d); setError(null); }).catch(e => setError(String(e.message ?? e)));
  }, [path]);
  useEffect(reload, [reload]);
  return { data, error, reload, setData };
}

export const money = (n?: number) => `$${(n ?? 0).toFixed(2)}`;
export const SECTION_SHORT: Record<string, string> = {
  Physics: "Phy", Chemistry: "Chem", "English Proficiency": "Eng", "Logical Reasoning": "LR", Mathematics: "Math",
};
