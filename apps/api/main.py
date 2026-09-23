from __future__ import annotations

from pathlib import Path

from .database import Database
from .job_repository import JobRepository
from .settings import ApiSettings
from .user_repository import UserRepository
from .forum_repository import ForumRepository


def create_app(settings: ApiSettings | None = None, *, agent_service=None):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles

    from apps.agent.web_service import WebAgentService
    from shiju.service.gpu_provider import ManualGpuProvider

    from .routes.agent import router as agent_router
    from .routes.auth import router as auth_router
    from .routes.conversations import router as conversations_router
    from .routes.folders import router as folders_router
    from .routes.profile import router as profile_router
    from .routes.public import router as public_router
    from .routes.worker import router as worker_router
    from .routes.forum import router as forum_router
    from .routes.admin import router as admin_router

    active = settings or ApiSettings.from_env()
    database = Database(active.database_url or active.database_path)
    database.initialize()
    users = UserRepository(database)
    users.seed_defaults()

    app = FastAPI(title="诗矩工具服务", version="0.2.0")
    # 兼容当前 FastAPI/Starlette 版本，避免依赖已移除的 add_event_handler。
    app.router.on_shutdown.append(database.close)
    app.state.settings = active
    app.state.jobs = JobRepository(database)
    app.state.users = users
    app.state.forum = ForumRepository(database)
    app.state.gpu_provider = ManualGpuProvider()
    project_root = Path(__file__).resolve().parents[2]
    if agent_service is not None:
        app.state.agent_service = agent_service
    elif active.web_agent_enabled:
        app.state.agent_service = WebAgentService.from_env(
            app.state.jobs,
            app.state.gpu_provider,
            project_root,
        )
    else:
        app.state.agent_service = None

    @app.middleware("http")
    async def limit_request_size(request: Request, call_next):
        length = request.headers.get("content-length")
        limit = 2 * 1024 * 1024 if request.url.path == "/v1/profile/me/avatar" else active.max_request_bytes
        if length and int(length) > limit:
            return JSONResponse(status_code=413, content={"detail": "request too large"})
        return await call_next(request)

    @app.get("/health/live", tags=["health"])
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready():
        database_status = "ok"
        try:
            database.check()
        except Exception:
            database_status = "error"
        payload = {
            "status": "ok" if database_status == "ok" else "degraded",
            "database": database_status,
            "gpu_provider": app.state.gpu_provider.status(),
            "worker_online": app.state.jobs.has_live_worker(),
        }
        if database_status != "ok":
            return JSONResponse(status_code=503, content=payload)
        return payload

    app.include_router(public_router)
    app.include_router(worker_router)
    app.include_router(agent_router)
    app.include_router(auth_router)
    app.include_router(conversations_router)
    app.include_router(folders_router)
    app.include_router(profile_router)
    app.include_router(forum_router)
    app.include_router(admin_router)

    @app.get("/", include_in_schema=False)
    def website():
        return RedirectResponse("/web/prosody-checker/#home")

    app.mount(
        "/Rhyme",
        StaticFiles(directory=project_root / "Rhyme"),
        name="rhyme-data",
    )
    app.mount(
        "/Songci_Meter",
        StaticFiles(directory=project_root / "Songci_Meter"),
        name="meter-data",
    )
    app.mount(
        "/web",
        StaticFiles(directory=project_root / "web", html=True),
        name="web",
    )
    avatar_dir = active.database_path.parent / "avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media/avatars", StaticFiles(directory=avatar_dir), name="avatars")
    return app


def main() -> None:
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8000, workers=1)


if __name__ == "__main__":
    main()
