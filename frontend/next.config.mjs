/**
 * Next.js configuration.
 *
 * The one non-default piece is the dev-time API proxy (Part 7 §5.1, the M26 compose row): the
 * browser talks to same-origin `/v1/*`, and in development Next rewrites that to the backend
 * service so there is no CORS surface and no hard-coded API host in client code. In production the
 * reverse proxy in front of the compose stack owns the same `/v1` prefix, so the client contract
 * ("call same-origin /v1") is identical in both environments. `API_PROXY_TARGET` defaults to the
 * compose service name; override it for a locally-run backend.
 */
const apiTarget = process.env.API_PROXY_TARGET ?? "http://backend:8000";

/**
 * The rewrite proxy clones each `/v1/*` request body up to this ceiling. Next's default is **10 MB**
 * (`middlewareClientMaxBodySize`), which silently truncates a larger upload and breaks the multipart
 * stream to the backend — the browser sees a bare `500` (ECONNRESET), never the app's own
 * `413 FILE_TOO_LARGE`. Uploads pass *through* this proxy, so its ceiling must sit **strictly above**
 * the backend's own upload ceiling (`XTALATE_MAX_UPLOAD_BYTES`, default 100 MB): if the proxy
 * truncated an oversize body down to the backend's exact limit, the backend would accept a corrupted
 * (silently truncated) file instead of refusing it. Keeping a fixed headroom above the backend
 * ceiling makes the backend the *sole* gate — either it accepts the whole file or it returns its
 * honest 413, and no upload is ever silently truncated (P1). The frontend must therefore be given the
 * same `XTALATE_MAX_UPLOAD_BYTES` the backend uses (compose passes it; self-hosting documents it).
 */
const backendMaxUploadBytes = Number(process.env.XTALATE_MAX_UPLOAD_BYTES) || 100 * 1024 * 1024;
const PROXY_HEADROOM_BYTES = 8 * 1024 * 1024; // > 0 so the backend, not the proxy, owns the gate.
const proxyClientMaxBodySize = backendMaxUploadBytes + PROXY_HEADROOM_BYTES;

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The single-container Hugging Face Spaces demo (v1.1 M39-S1) runs the standalone Next server
  // (`.next/standalone`) inside the same container as the backend, so the frontend needs the
  // self-contained bundle `output: "standalone"` produces. Purely additive: `next dev` ignores it,
  // and the ordinary `next build && next start` self-host still gets a working `.next/`, so no
  // existing flow (compose dev stack, CI production build, docker-compose.prod.yml edge build)
  // changes behaviour.
  output: "standalone",
  experimental: {
    // Raise the proxy body-clone ceiling above the backend's upload limit (see above). Without this
    // every upload over Next's 10 MB default fails with an opaque 500 before reaching the API.
    middlewareClientMaxBodySize: proxyClientMaxBodySize,
  },
  async rewrites() {
    return [
      {
        source: "/v1/:path*",
        destination: `${apiTarget}/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
