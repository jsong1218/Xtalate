import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

/**
 * The typed `/v1` API client (MASTER_SPEC Part 7 §5.1).
 *
 * Every endpoint, request body, query param, and response type comes from `./schema` — generated
 * from the committed `docs/openapi.json` by `npm run gen:api` (D90). There are **no hand-written
 * endpoint types**: if this file needs a type the generated schema does not have, the OpenAPI
 * artifact is wrong and is fixed there (the M26 go/no-go checkpoint).
 *
 * The client is **same-origin** by contract. OpenAPI paths already carry the `/v1` prefix, so a
 * browser request goes to `/v1/...` on the app's own origin; `next.config.mjs` proxies that to the
 * backend in dev, and the production reverse proxy routes it — the client code is identical in both.
 * On the server (RSC / route handlers) there is no origin, so we fall back to the in-cluster
 * backend URL.
 */
const baseUrl =
  typeof window === "undefined"
    ? (process.env.INTERNAL_API_URL ?? "http://backend:8000")
    : "";

export const apiClient = createClient<paths>({ baseUrl });

/**
 * The generated response/request models, keyed by name — e.g. `Schemas["LimitsResponse"]`,
 * `Schemas["JobEnvelope"]`. Response bodies embed the pydantic report models verbatim (Part 6
 * preamble), so components never fork into parallel DTOs.
 */
export type Schemas = components["schemas"];
