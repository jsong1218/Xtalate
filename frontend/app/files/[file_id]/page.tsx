import { redirect } from "next/navigation";

/**
 * Legacy route (UI redesign S2, D244): the inspection surface now lives at `/f/[file_id]` (the
 * workspace's Inspect tab). This route file stays so every bookmarked `/files/[id]` URL keeps
 * resolving — a server redirect, no 404s.
 */
export default async function LegacyFilePage({
  params,
}: {
  params: Promise<{ file_id: string }>;
}) {
  const { file_id } = await params;
  redirect(`/f/${file_id}`);
}
