import type { NextConfig } from "next";

const API = process.env.BITQGEN_API ?? "http://127.0.0.1:8000";

const config: NextConfig = {
  compress: false, // gzip would buffer the SSE activity stream
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API}/api/:path*` },
      { source: "/static/:path*", destination: `${API}/static/:path*` },
      { source: "/jobs/:id/view/:path*", destination: `${API}/jobs/:id/view/:path*` },
      { source: "/jobs/:id/files/:path*", destination: `${API}/jobs/:id/files/:path*` },
      { source: "/jobs/:id/export", destination: `${API}/jobs/:id/export` },
      { source: "/jobs/:id/export/:path*", destination: `${API}/jobs/:id/export/:path*` },
      { source: "/corpus/:id/view/:path*", destination: `${API}/corpus/:id/view/:path*` },
      { source: "/corpus/:id/export", destination: `${API}/corpus/:id/export` },
    ];
  },
};
export default config;
