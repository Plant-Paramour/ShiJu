from __future__ import annotations

from pathlib import Path

from .framework import AgentSession
from .jobs import HttpPoetryJobs
from .openai_client import OpenAICompatibleChatModel
from .gateway import ModelGateway
from .settings import AgentSettings
from .tools import AgentToolbox


def create_session(settings: AgentSettings | None = None) -> AgentSession:
    active = settings or AgentSettings.from_env()
    if active.gateway_config_path:
        model = ModelGateway.from_toml(active.gateway_config_path, max_attempts=active.gateway_max_attempts)
    else:
        model = ModelGateway.single(base_url=active.llm_base_url, api_key=active.llm_api_key, model=active.llm_model, timeout_seconds=active.request_timeout_seconds)
    jobs = HttpPoetryJobs(
        base_url=active.poetry_api_base_url,
        token=active.poetry_api_token,
    )
    project_root = Path(__file__).resolve().parents[2]
    toolbox = AgentToolbox(project_root, jobs)
    return AgentSession(model, toolbox, max_tool_rounds=active.max_tool_rounds)


def main() -> None:
    try:
        session = create_session()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    print("诗矩 Agent 已启动。输入 /reset 清空会话，输入 /exit 退出。")
    while True:
        try:
            user_input = input("\n你：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user_input in {"/exit", "/quit"}:
            break
        if user_input == "/reset":
            session.reset()
            print("会话已清空。")
            continue
        if not user_input:
            continue
        try:
            response = session.respond(user_input)
        except Exception as exc:
            print(f"\n系统：{exc}")
            continue
        print(f"\n诗矩：{response}")


if __name__ == "__main__":
    main()

