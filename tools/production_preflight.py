"""Validate local production-like configuration without contacting model APIs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from apps.agent.gateway import ModelGateway


def validate_gateway_config(path: str | Path, *, require_secrets: bool = False) -> list[str]:
    gateway = ModelGateway.from_toml(path)
    errors = []
    for item in gateway.status():
        if require_secrets and not os.getenv(next(
            endpoint.config.secret_ref for endpoint in gateway._states
            if endpoint.config.provider_id == item["provider_id"] and endpoint.config.model == item["model"]
        ), ""):
            errors.append(f"端点密钥未配置: {item['provider_id']}/{item['model']}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="检查诗矩本地生产配置")
    parser.add_argument("--gateway-config", type=Path)
    parser.add_argument("--require-secrets", action="store_true")
    args = parser.parse_args()
    errors: list[str] = []
    if args.gateway_config:
        if not args.gateway_config.is_file():
            errors.append(f"网关配置不存在: {args.gateway_config}")
        else:
            try:
                errors.extend(validate_gateway_config(args.gateway_config, require_secrets=args.require_secrets))
            except (OSError, ValueError) as exc:
                errors.append(f"网关配置无效: {exc}")
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("生产配置预检通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
