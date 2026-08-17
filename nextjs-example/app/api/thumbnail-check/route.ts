// Drop this in your Next.js project at: app/api/thumbnail-check/route.ts
//
// It proxies uploads to the Python metadata service. Keeping the service
// server-side means the API key never reaches the browser and you avoid CORS
// entirely -- the browser only ever talks to your own Next.js origin.
//
// .env.local:
//   METADATA_SERVICE_URL=http://127.0.0.1:8000
//   METADATA_API_KEY=your-secret-key

import { NextRequest, NextResponse } from "next/server";

const SERVICE_URL = process.env.METADATA_SERVICE_URL ?? "http://127.0.0.1:8000";
const API_KEY = process.env.METADATA_API_KEY ?? "";
const MAX_BYTES = 25 * 1024 * 1024;

export const runtime = "nodejs"; // needs Node streams, not the edge runtime

type Finding = {
  severity: "hard" | "soft";
  label: string;
  location: string;
  matched: string;
};

type CheckResult = {
  verdict: string;
  ai_detected: boolean;
  suspicious: boolean;
  clean: boolean;
  format: string;
  bytes: number;
  findings: Finding[];
  benign_signals: string[];
};

function authHeaders(): HeadersInit {
  return API_KEY ? { Authorization: `Bearer ${API_KEY}` } : {};
}

export async function POST(req: NextRequest) {
  const incoming = await req.formData();
  const file = incoming.get("file");

  if (!(file instanceof File)) {
    return NextResponse.json({ error: "no file uploaded" }, { status: 400 });
  }
  if (file.size === 0) {
    return NextResponse.json({ error: "file is empty" }, { status: 400 });
  }
  if (file.size > MAX_BYTES) {
    return NextResponse.json({ error: "file too large" }, { status: 413 });
  }

  // `?clean=1` strips the metadata and streams the cleaned image straight back.
  const wantsClean = req.nextUrl.searchParams.get("clean") === "1";
  const endpoint = wantsClean ? "/clean" : "/check";

  const body = new FormData();
  body.append("file", file, file.name);

  let res: Response;
  try {
    res = await fetch(`${SERVICE_URL}${endpoint}`, {
      method: "POST",
      headers: authHeaders(),
      body,
      signal: AbortSignal.timeout(30_000),
    });
  } catch (err) {
    // The Python service being down should read as a clear 502, not a crash.
    return NextResponse.json(
      { error: "metadata service unreachable", detail: String(err) },
      { status: 502 },
    );
  }

  if (!res.ok) {
    const detail = await res.text();
    return NextResponse.json(
      { error: "metadata service error", detail },
      { status: res.status },
    );
  }

  if (wantsClean) {
    // Pass the image through, preserving the verdict headers the service set.
    return new NextResponse(await res.arrayBuffer(), {
      headers: {
        "Content-Type": res.headers.get("content-type") ?? "application/octet-stream",
        "Content-Disposition":
          res.headers.get("content-disposition") ?? "inline",
        "X-Verdict-Before": res.headers.get("x-verdict-before") ?? "",
        "X-Verdict-After": res.headers.get("x-verdict-after") ?? "",
        "X-Bytes-Removed": res.headers.get("x-bytes-removed") ?? "0",
      },
    });
  }

  const result: CheckResult = await res.json();

  // Only `hard` findings are what platforms actually read and label on.
  // `soft` ones mean an AI tool touched the file without declaring anything.
  const blocking = result.findings.filter((f) => f.severity === "hard");

  return NextResponse.json({
    safeToUpload: !result.ai_detected,
    verdict: result.verdict,
    willBeLabeled: result.ai_detected,
    reasons: blocking.map((f) => ({ what: f.label, where: f.location })),
    traces: result.findings
      .filter((f) => f.severity === "soft")
      .map((f) => f.label),
    format: result.format,
    bytes: result.bytes,
  });
}
