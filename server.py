#!/usr/bin/env python3
"""
server.py -- HTTP service around the AI-metadata checker, for calling from
Next.js (or anything else that speaks HTTP).

Run:
    .\.venv\Scripts\python.exe server.py                 # http://127.0.0.1:8000
    .\.venv\Scripts\python.exe server.py --port 9000 --host 0.0.0.0

Endpoints (all POST bodies are multipart/form-data with a `file` field):
    GET  /health          liveness + version
    POST /check           -> JSON verdict + findings + metadata dump
    POST /clean           -> the stripped image bytes (image/png etc.)
    POST /clean/json      -> JSON with the stripped image base64-encoded

Auth: if API_KEY is set in the environment, every request must send
      `Authorization: Bearer <key>`. Unset means open -- fine for localhost,
      not for anything reachable from outside.
"""

from __future__ import annotations

import base64
import os
import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

import ai_metadata_check as checker

API_KEY = os.environ.get("API_KEY", "")
MAX_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 25 * 1024 * 1024))
ALLOWED_ORIGINS = [o for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o]

MIME_BY_FORMAT = {"JPEG": "image/jpeg", "PNG": "image/png", "WebP": "image/webp"}

app = FastAPI(
    title="AI metadata checker",
    version="1.0.0",
    description="Detects and strips AI-generation markers (C2PA, IPTC "
                "digitalSourceType, generator tags) in images.",
)

# Only needed if a browser calls this directly. Server-side Next.js route
# handlers are unaffected by CORS, which is the safer way to call it.
if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["POST", "GET"],
        allow_headers=["*"],
    )


def require_key(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Bearer check. Constant-time compare so the key cannot be timed out.

    `Header()` is load-bearing: without it FastAPI reads `authorization` as a
    query parameter and every request fails auth regardless of its headers.
    """
    if not API_KEY:
        return
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(401, "missing bearer token")
    if not secrets.compare_digest(authorization[len(prefix):], API_KEY):
        raise HTTPException(401, "invalid api key")


async def read_upload(file: UploadFile) -> bytes:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty file")
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, f"file exceeds {MAX_BYTES:,} bytes")
    return raw


Auth = Annotated[None, Depends(require_key)]


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "ai-metadata-checker", "version": app.version,
            "auth_required": bool(API_KEY), "max_upload_bytes": MAX_BYTES}


@app.post("/check")
async def check(_: Auth, file: Annotated[UploadFile, File()],
                include_content: Annotated[bool, Form()] = True) -> dict:
    """Analyse an image. Returns the verdict plus every metadata block."""
    raw = await read_upload(file)
    try:
        return checker.analyze(raw, file.filename or "upload",
                               include_content=include_content)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/clean")
async def clean_binary(_: Auth, file: Annotated[UploadFile, File()],
                       keep_icc: Annotated[bool, Form()] = True) -> Response:
    """Strip metadata and return the cleaned image itself.

    Verdicts ride along in headers so the caller learns what was removed
    without a second request.
    """
    raw = await read_upload(file)
    try:
        result = checker.clean(raw, file.filename or "upload", keep_icc=keep_icc)
    except ValueError as exc:
        raise HTTPException(415, str(exc))

    if not result["verified"]:
        # Never hand back a file we could not confirm is clean.
        raise HTTPException(500, "strip did not remove every marker")

    fmt = result["before"]["format"]
    return Response(
        content=result["data"],
        media_type=MIME_BY_FORMAT.get(fmt, "application/octet-stream"),
        headers={
            "X-Verdict-Before": result["before"]["verdict"],
            "X-Verdict-After": result["after"]["verdict"],
            "X-Bytes-Removed": str(result["bytes_removed"]),
            "X-Findings": str(len(result["before"]["findings"])),
            "Content-Disposition":
                f'inline; filename="{_clean_name(file.filename)}"',
        },
    )


@app.post("/clean/json")
async def clean_json(_: Auth, file: Annotated[UploadFile, File()],
                     keep_icc: Annotated[bool, Form()] = True) -> dict:
    """Same as /clean but JSON, with the image base64-encoded.

    Easier to consume from a Next.js route handler that wants the verdict and
    the file in one response; costs ~33% more bytes on the wire.
    """
    raw = await read_upload(file)
    try:
        result = checker.clean(raw, file.filename or "upload", keep_icc=keep_icc)
    except ValueError as exc:
        raise HTTPException(415, str(exc))

    return {
        "filename": _clean_name(file.filename),
        "verified": result["verified"],
        "bytes_removed": result["bytes_removed"],
        "before": result["before"],
        "after": result["after"],
        "image_base64": base64.b64encode(result["data"]).decode(),
        "mime": MIME_BY_FORMAT.get(result["before"]["format"],
                                   "application/octet-stream"),
    }


def _clean_name(name: str | None) -> str:
    stem = os.path.basename(name or "image")
    root, dot, ext = stem.rpartition(".")
    return f"{root}.clean.{ext}" if dot else f"{stem}.clean"


if __name__ == "__main__":
    import argparse

    import uvicorn

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true", help="restart on code changes")
    a = p.parse_args()

    if a.host != "127.0.0.1" and not API_KEY:
        print("WARNING: listening beyond localhost with no API_KEY set.")

    uvicorn.run("server:app" if a.reload else app,
                host=a.host, port=a.port, reload=a.reload)
