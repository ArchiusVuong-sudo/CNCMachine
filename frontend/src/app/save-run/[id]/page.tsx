import { Workspace } from "@/components/workspace/workspace";

/**
 * Saved-run route — `/save-run/<id>` renders the workspace pinned to one
 * persisted analysis. The CoFab logo returns to `/` (dashboard); selecting a
 * different run in the panel navigates between save-run URLs.
 */
export default async function SaveRunPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <Workspace savedRunId={id} />;
}
