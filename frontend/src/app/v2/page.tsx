// Fresh entry point alongside `/` for cases where the edge has the old `/`
// prerender pinned. Renders the same Workspace, served as a dynamic route so
// the edge doesn't cache it with a long TTL.
import { Workspace } from "@/components/workspace/workspace";

export const dynamic = "force-dynamic";

export default function WorkspaceV2Page() {
  return <Workspace />;
}
