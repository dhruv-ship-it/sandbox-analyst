"""The FastAPI app: health, dataset upload, examples, and the run lifecycle (incl. SSE).

`create_app` takes an already-constructed `llm` and `sandbox_factory` so
tests can inject `FakeLLM`/`FakeSandbox` directly (CLAUDE.md rule 6: unit
tests never touch the network). `build_app` wires the real backends from
`Settings` for `sa serve` and the Docker image.
"""

import asyncio
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from sandbox_analyst.agent.profile import profile_csv
from sandbox_analyst.config import Settings
from sandbox_analyst.llm import LLMClient, make_llm
from sandbox_analyst.sandbox import Sandbox, make_sandbox

from .datasets import DatasetError, DatasetStore, load_example_bytes, load_examples, profile_summary
from .limits import RateLimiter, client_ip
from .runs import TERMINAL_STATUSES, RunStore, artifact_path, build_summary
from .schemas import RunCreateRequest

WEB_DIST_DIR = Path("web/dist")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
}

PLACEHOLDER_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sandbox Analyst</title>
</head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 3rem auto;
      padding: 0 1rem;">
  <h1>Sandbox Analyst</h1>
  <p>An AI data analyst: upload a CSV, ask a question, and get an
  evidence-checked answer from code that ran in a sandboxed,
  network-isolated environment.</p>
  <p><strong>UI coming soon.</strong></p>
  <p><a href="/api/health">/api/health</a></p>
</body>
</html>
"""


class ApiError(Exception):
    """A client-facing error with an explicit status code, carrying {error, detail}."""

    def __init__(self, status_code: int, error: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.error = error
        self.detail = detail


def _resolve_version(settings: Settings) -> str:
    if settings.app_version:
        return settings.app_version
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        sha = proc.stdout.strip()
        if sha:
            return sha
    except Exception:
        pass
    return "unknown"


def _validation_detail(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "invalid request"
    first = errors[0]
    loc = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
    message = first.get("msg", "invalid value")
    return f"{loc}: {message}" if loc else message


def _sse_message(event_dict: dict) -> str:
    return f"data: {json.dumps(event_dict)}\n\n"


def create_app(
    settings: Settings,
    *,
    llm: LLMClient,
    sandbox_factory: Callable[[], Sandbox],
) -> FastAPI:
    data_dir = Path(settings.sa_data_dir)
    trace_dir = data_dir / "traces"

    dataset_store = DatasetStore(
        data_dir,
        ttl_s=settings.api_upload_ttl_s,
        max_upload_mb=settings.api_max_upload_mb,
        max_rows=settings.api_max_rows,
        max_cols=settings.api_max_cols,
    )
    run_store = RunStore(max_workers=settings.sa_max_concurrent_runs)
    limiter = RateLimiter(
        per_ip_hour=settings.sa_rate_limit_per_ip_hour,
        per_ip_day=settings.sa_rate_limit_per_ip_day,
        global_day=settings.sa_rate_limit_global_day,
        max_concurrent=settings.sa_max_concurrent_runs,
    )
    version = _resolve_version(settings)

    app = FastAPI(title="Sandbox Analyst", description="An AI data analyst over a CSV.")

    # --- errors: every failure comes back as {"error": ..., "detail": ...} ---

    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"error": exc.error, "detail": exc.detail}
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": "validation_error", "detail": _validation_detail(exc)},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> FileResponse | JSONResponse:
        if (
            exc.status_code == 404
            and WEB_DIST_DIR.is_dir()
            and not request.url.path.startswith("/api/")
        ):
            return FileResponse(WEB_DIST_DIR / "index.html")
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code, content={"error": "http_error", "detail": detail}
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": "an unexpected error occurred"},
        )

    # --- security headers + a body-size guard on every request ---

    max_request_bytes = int(settings.api_max_upload_mb * 1024 * 1024) + 4096

    @app.middleware("http")
    async def _security_and_size(request: Request, call_next):
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > max_request_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "error": "request_too_large",
                    "detail": f"body is {declared} bytes, over the {max_request_bytes} byte limit",
                },
                headers=SECURITY_HEADERS,
            )
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    # --- routes ---

    @app.get("/api/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "version": version,
            "provider": settings.sa_llm_provider,
            "model": settings.sa_llm_model or "n/a",
            "sandbox": settings.sa_sandbox,
        }

    @app.post("/api/datasets")
    async def upload_dataset(file: UploadFile = File(...)) -> dict:  # noqa: B008
        data = await file.read()
        try:
            profile = dataset_store.validate_and_profile(file.filename or "", data)
        except DatasetError as exc:
            raise ApiError(400, "invalid_dataset", str(exc)) from exc
        dataset_id = dataset_store.store(file.filename or "dataset.csv", data)
        return {"dataset_id": dataset_id, **profile_summary(profile)}

    @app.get("/api/examples")
    async def list_examples() -> dict:
        return load_examples()

    @app.post("/api/examples/{name}/load")
    async def load_example(name: str) -> dict:
        found = load_example_bytes(name)
        if found is None:
            raise ApiError(404, "not_found", f"no example dataset named {name!r}")
        file_name, data = found
        profile = profile_csv(data, file_name)
        dataset_id = dataset_store.store(file_name, data)
        return {"dataset_id": dataset_id, **profile_summary(profile)}

    @app.post("/api/runs")
    async def create_run(request: Request, body: RunCreateRequest) -> dict:
        stored = dataset_store.get(body.dataset_id)
        if stored is None:
            raise ApiError(404, "not_found", "dataset not found or expired")

        ip = client_ip(request, settings.sa_trust_proxy)
        reason = limiter.reserve(ip)
        if reason is not None:
            raise ApiError(429, "rate_limited", reason)

        try:
            data = dataset_store.read_bytes(stored)
            loop = asyncio.get_running_loop()
            record = run_store.start(
                dataset_id=body.dataset_id,
                question=body.question,
                client_ip=ip,
                csv_bytes=data,
                file_name=stored.file_name,
                llm=llm,
                sandbox_factory=sandbox_factory,
                settings=settings,
                trace_dir=trace_dir,
                loop=loop,
                limiter=limiter,
            )
        except Exception:
            limiter.release()
            raise
        return {"run_id": record.run_id}

    @app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: str) -> StreamingResponse:
        record = run_store.get(run_id)
        if record is None:
            raise ApiError(404, "not_found", "run not found")

        async def generator():
            snapshot, queue = record.subscribe()
            try:
                for event_dict in snapshot:
                    yield _sse_message(event_dict)
                    if event_dict["type"] == "run_finished":
                        return
                with record.lock:
                    already_done = record.status in TERMINAL_STATUSES
                if already_done:
                    return
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    if item.get("type") == "__closed__":
                        return
                    yield _sse_message(item)
                    if item["type"] == "run_finished":
                        return
            finally:
                record.unsubscribe(queue)

        return StreamingResponse(generator(), media_type="text/event-stream")

    @app.get("/api/runs/{run_id}")
    async def run_summary(run_id: str) -> dict:
        record = run_store.get(run_id)
        if record is None:
            raise ApiError(404, "not_found", "run not found")
        return build_summary(record)

    @app.get("/api/runs/{run_id}/artifacts/{name}")
    async def run_artifact(run_id: str, name: str) -> FileResponse:
        record = run_store.get(run_id)
        if record is None:
            raise ApiError(404, "not_found", "run not found")
        path = artifact_path(record, name)
        if path is None:
            raise ApiError(404, "not_found", "artifact not found")
        return FileResponse(path, media_type="image/png")

    @app.get("/api/runs/{run_id}/trace")
    async def run_trace(run_id: str) -> FileResponse:
        record = run_store.get(run_id)
        if record is None:
            raise ApiError(404, "not_found", "run not found")
        trace_path = trace_dir / f"{run_id}.jsonl"
        if not trace_path.is_file():
            raise ApiError(404, "not_found", "no trace recorded yet")
        return FileResponse(
            trace_path, media_type="application/x-ndjson", filename=f"{run_id}.jsonl"
        )

    # --- static UI (Prompt 6 builds web/dist) or a minimal placeholder ---

    if WEB_DIST_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIST_DIR), html=True), name="web")
    else:

        @app.get("/", response_class=HTMLResponse)
        async def placeholder() -> str:
            return PLACEHOLDER_HTML

    return app


def build_app(settings: Settings) -> FastAPI:
    """Wire real LLM/sandbox backends from `settings` -- used by `sa serve` and Docker."""
    llm = make_llm(settings)
    data_dir = Path(settings.sa_data_dir)

    def sandbox_factory() -> Sandbox:
        if settings.sa_sandbox == "modal":
            from sandbox_analyst.sandbox.modal_sandbox import ModalSandbox

            return ModalSandbox(settings, ledger_path=data_dir / "sandbox_ledger.jsonl")
        return make_sandbox(settings)

    return create_app(settings, llm=llm, sandbox_factory=sandbox_factory)
