// Calls to the Python server, each carrying the signed-in user's token.

import { supabase } from "./supabase";

export async function accessToken() {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? "";
}

async function authHeaders() {
  const token = await accessToken();
  return token ? { Authorization: `Bearer ${token}` } : ({} as Record<string, string>);
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

interface ApiOptions {
  method?: string;
  body?: unknown;
  form?: FormData;
}

export async function api<T = any>(path: string, { method = "GET", body, form }: ApiOptions = {}): Promise<T> {
  const headers = await authHeaders();
  const opts: RequestInit = { method, headers };
  if (form) opts.body = form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : null;
    throw new ApiError(detail ?? `request failed (${res.status})`, res.status);
  }
  return data;
}

/** A recording or photo as a local URL: <img> and <audio> can't send the token themselves. */
export async function fileUrl(path: string) {
  const res = await fetch(path, { headers: await authHeaders() });
  if (!res.ok) throw new ApiError("could not load the file", res.status);
  return URL.createObjectURL(await res.blob());
}

let _config: any = null;
export async function config() {
  if (!_config) _config = await api("/api/config");
  return _config;
}
