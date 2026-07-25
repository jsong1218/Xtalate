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

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
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
