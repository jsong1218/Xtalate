import { redirect } from "next/navigation";

/**
 * Legacy route (UI redesign S2, D244): upload lives on the landing (`/`) — the hero's "Convert a
 * file" opens the dropzone there — so this route file stays only so bookmarked `/convert` URLs keep
 * resolving. A server redirect, no 404s.
 */
export default function LegacyConvertPage() {
  redirect("/");
}
