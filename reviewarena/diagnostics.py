"""Private, metadata-only diagnostics for live manuscript jobs."""
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import time
from uuid import uuid4


LOG_DIR = Path(__file__).resolve().parents[1] / "data/private/logs"
_run = ContextVar("review_log", default=None)
_stage = ContextVar("review_stage", default="")
_note = "Review log ID: "


def event(kind, **fields):
    run = _run.get()
    if run is None:
        return
    run_id, started = run
    row = dict(time=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
               elapsed_s=round(time.monotonic() - started, 3), stage=_stage.get(),
               event=kind, **fields)
    try:
        LOG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(LOG_DIR / (run_id + ".jsonl"), "a", encoding="utf-8",
                  opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
            stream.write(json.dumps(row) + "\n")
    except OSError:
        logging.getLogger(__name__).warning("Unable to write review diagnostics for %s", run_id)


def stage(label):
    if _run.get() is not None:
        _stage.set(label)
        event("stage")


def model_response(response, started):
    if _run.get() is None:
        return
    fields = dict(http_status=response.status_code, duration_s=round(time.monotonic()-started, 3))
    request_id = response.headers.get("request-id") or response.headers.get("x-request-id", "")
    if re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", request_id):
        fields["request_id"] = request_id
    retry_after = response.headers.get("Retry-After", "")
    if re.fullmatch(r"[0-9]{1,9}", retry_after):
        fields["retry_after_s"] = int(retry_after)
    if response.status_code >= 400:
        try:
            body = response.json()
        except ValueError:
            body = None
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            category = error.get("type")
            if category in ("overloaded_error", "rate_limit_error", "api_error", "invalid_request_error",
                            "timeout_error", "authentication_error", "permission_error", "billing_error"):
                fields["provider_error_type"] = category
    event("model_http", **fields)


def failure(exc, kind="failed"):
    if _run.get() is None:
        return
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            failure(child, kind)
        return
    frames = []
    frame = exc.__traceback__
    while frame:
        code = frame.tb_frame.f_code
        path = Path(code.co_filename)
        if path.parent.name == "reviewarena":
            frames.append(f"{path.name}:{frame.tb_lineno}:{code.co_name}")
        frame = frame.tb_next
    response = getattr(exc, "response", None)
    event(kind, error=type(exc).__name__, http_status=getattr(response, "status_code", None),
          location=frames)


async def traced(action, coro):
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:12]
    token = _run.set((run_id, time.monotonic()))
    stage_token = _stage.set(action)
    try:
        event("started", model=os.environ.get("REVIEWARENA_MODEL", "default_model"))
        result = await coro
        partial = isinstance(result, dict) and bool((result.get("meta_review") or {}).get("error"))
        event("partial" if partial else "completed")
        return result
    except Exception as exc:
        failure(exc)
        exc.add_note(_note + run_id)
        raise
    finally:
        _stage.reset(stage_token)
        _run.reset(token)


def error_text(exc):
    return "\n\n".join([str(exc), *(n for n in getattr(exc, "__notes__", []) if n.startswith(_note))])
