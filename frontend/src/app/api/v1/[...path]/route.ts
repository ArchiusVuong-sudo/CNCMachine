/**
 * Catch-all proxy to the Python FastAPI backend.
 *
 * Every browser-side fetch to ``/api/v1/...`` lands here and gets
 * forwarded to ``${PYTHON_SERVICE_URL}/v1/...`` 1:1. This is the single
 * place the frontend talks to the backend — keeps the Python upstream
 * URL off the client bundle and lets us add auth/logging later in one
 * spot.
 *
 * SSE pass-through: when the upstream responds with
 * ``text/event-stream`` the body is forwarded directly without
 * wrapping in ``NextResponse`` (which would buffer the stream).
 */
import { NextRequest } from "next/server";

export const dynamic     = "force-dynamic";
export const maxDuration = 600;

const HOP_BY_HOP = new Set([
  "host", "connection", "keep-alive", "transfer-encoding",
  "upgrade", "proxy-authorization", "proxy-authenticate",
  "te", "trailers", "content-length",
]);

function forwardHeaders(src: Headers): Headers {
  const out = new Headers();
  src.forEach((value, key) => {
    if (HOP_BY_HOP.has(key.toLowerCase())) return;
    out.set(key, value);
  });
  return out;
}

async function proxy(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path }     = await params;
  const pythonBase   = (process.env.PYTHON_SERVICE_URL ?? "http://localhost:8001").replace(/\/$/, "");
  const search       = new URL(req.url).search;
  const upstreamUrl  = `${pythonBase}/v1/${path.join("/")}${search}`;

  const init: RequestInit & { duplex?: "half" } = {
    method:  req.method,
    headers: forwardHeaders(req.headers),
    signal:  req.signal,
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body   = req.body;
    init.duplex = "half";
  }

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, init);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return new Response(
      JSON.stringify({ error: `proxy: upstream unreachable — ${msg}` }),
      { status: 502, headers: { "Content-Type": "application/json" } },
    );
  }

  const ctype = upstream.headers.get("content-type") ?? "";

  if (ctype.includes("text/event-stream")) {
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type":      "text/event-stream",
        "Cache-Control":     "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection":        "keep-alive",
      },
    });
  }

  return new Response(upstream.body, {
    status:  upstream.status,
    headers: { "Content-Type": ctype || "application/octet-stream" },
  });
}

export {
  proxy as GET,
  proxy as POST,
  proxy as PATCH,
  proxy as PUT,
  proxy as DELETE,
};
