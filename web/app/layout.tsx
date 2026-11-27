import type { Metadata } from "next";
import Script from "next/script";
import { Instrument_Sans, Source_Serif_4, JetBrains_Mono } from "next/font/google";
import Nav from "@/components/Nav";
import "./globals.css";

const sans = Instrument_Sans({ subsets: ["latin"], variable: "--f-sans" });
const serif = Source_Serif_4({ subsets: ["latin"], variable: "--f-serif" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--f-mono" });

export const metadata: Metadata = { title: "bitQgen studio", description: "BITSAT question-paper studio" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${serif.variable} ${mono.variable}`}>
      <head><link rel="stylesheet" href="/static/katex/katex.min.css" /></head>
      <body>
        <Script src="/static/katex/katex.min.js" strategy="beforeInteractive" />
        <Script src="/static/katex/auto-render.min.js" strategy="afterInteractive" />
        <Nav />
        <main>{children}</main>
      </body>
    </html>
  );
}
