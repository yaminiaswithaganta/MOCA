// The Supabase client. Its address and public key come from the server, so one .env
// configures everything and the same build works on any deployment.

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export interface PublicConfig {
  supabase_url: string;
  supabase_anon_key: string;
  google_login: boolean;
}

export let publicConfig: PublicConfig;
export let supabase: SupabaseClient;

export async function initSupabase() {
  const res = await fetch("/api/public-config");
  if (!res.ok) throw new Error("The app server isn't responding.");
  publicConfig = await res.json();
  if (!publicConfig.supabase_url || !publicConfig.supabase_anon_key) {
    throw new Error("Supabase isn't set up yet: add its keys to the .env file and restart the server.");
  }
  supabase = createClient(publicConfig.supabase_url, publicConfig.supabase_anon_key);
}
