"use client";
import { useEffect, useRef } from "react";

declare global { interface Window { renderMathInElement?: (el: HTMLElement, o: object) => void } }

export function renderMath(el: HTMLElement | null) {
  if (!el) return;
  const go = () => window.renderMathInElement?.(el, {
    delimiters: [{ left: "$$", right: "$$", display: true }, { left: "$", right: "$", display: false }],
    throwOnError: false,
  });
  if (window.renderMathInElement) go(); else setTimeout(go, 300);
}

export default function MathHtml({ html, className, as = "div" }: { html: string; className?: string; as?: "div" | "span" }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => renderMath(ref.current), [html]);
  const Tag = as as "div";
  return <Tag ref={ref as React.RefObject<HTMLDivElement>} className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}
