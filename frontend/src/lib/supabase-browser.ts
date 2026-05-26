import { createClient, type SupabaseClient } from "@supabase/supabase-js";

/**
 * Browser-side Supabase client used for direct Storage uploads (bucket
 * "parts") and client-side signed-URL generation. The bytes go straight
 * FE → Storage so they never buffer through our API proxy.
 *
 * Key naming is tolerant on purpose: newer Supabase projects expose a
 * *publishable* key (``sb_publishable_…``) while older ones call the same
 * public key the *anon* key. We accept either env var name so the app works
 * regardless of which the deployment's ``.env.local`` defines:
 *
 *   NEXT_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co
 *   NEXT_PUBLIC_SUPABASE_ANON_KEY=…         (or)
 *   NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=…
 *
 * Both are public-by-design (they ship in the browser bundle); never put the
 * service-role key here.
 */
export function createSupabaseBrowserClient(): SupabaseClient {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key =
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ??
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

  if (!url || !key) {
    throw new Error(
      "Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL and " +
        "NEXT_PUBLIC_SUPABASE_ANON_KEY (or NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY) " +
        "in frontend/.env.local.",
    );
  }

  return createClient(url, key);
}
