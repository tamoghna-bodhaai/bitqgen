"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [["/", "Generate"], ["/corpus", "Past papers"], ["/syllabus", "Syllabus"], ["/models", "Models"]];

export default function Nav() {
  const path = usePathname();
  const on = (h: string) => (h === "/" ? path === "/" || path.startsWith("/jobs") : path.startsWith(h));
  return (
    <header className="nav">
      <Link href="/" className="brand" aria-label="bitQgen studio home">
        <span className="brand-mark" aria-hidden><i /><i className="f" /><i /><i /></span>
        bitQgen
      </Link>
      <nav>{LINKS.map(([h, l]) => <Link key={h} href={h} className={on(h) ? "on" : ""}>{l}</Link>)}</nav>
    </header>
  );
}
