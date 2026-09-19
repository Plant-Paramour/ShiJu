from __future__ import annotations

from .database import Database
from .job_repository import JobRepository
from .settings import ApiSettings


def create_app(settings: ApiSettings | None = None):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    from shiju.service.gpu_provider import ManualGpuProvider

    from .routes.public import router as public_router
    from .routes.worker import router as worker_router

    active = settings or ApiSettings.from_env()
    database = Database(active.database_path)
    database.initialize()

    app = FastAPI(title="诗矩工具服务", version="0.2.0")
    app.state.settings = active
    app.state.jobs = JobRepository(database)
    app.state.gpu_provider = ManualGpuProvider()

    @app.middleware("http")
    async def limit_request_size(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and int(length) > active.max_request_bytes:
            return JSONResponse(status_code=413, content={"detail": "request too large"})
        return await call_next(request)

    @app.get("/health/live", tags=["health"])
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready():
        return {
            "status": "ok",
            "gpu_provider": app.state.gpu_provider.status(),
            "worker_online": app.state.jobs.has_live_worker(),
        }

    app.include_router(public_router)
    app.include_router(worker_router)
    return app


def main() -> None:
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8000, workers=1)


if __name__ == "__main__":
    main()

