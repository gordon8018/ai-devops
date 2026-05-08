"""Detect dev server start command and port from workspace files."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServerConfig:
    start_cmd: str
    port: int
    env: dict[str, str]
    framework: str


_PORT_PATTERNS: list[re.Pattern] = [
    re.compile(r"PORT\s*=\s*(\d{4,5})"),
    re.compile(r'"port"\s*:\s*(\d{4,5})'),
    re.compile(r"port\s*=\s*(\d{4,5})"),
    re.compile(r":(\d{4,5})"),
]

_DEFAULT_PORTS: dict[str, int] = {
    "next": 3000,
    "vite": 5173,
    "react-scripts": 3000,
    "node": 3000,
    "django": 8000,
    "flask": 5000,
    "fastapi": 8000,
    "go": 8080,
    "rust": 8080,
}

# (detection_file, default_cmd, framework)
_START_CMD_CANDIDATES: list[tuple[str, str, str]] = [
    ("vite.config.ts",  "npm run dev", "vite"),
    ("vite.config.js",  "npm run dev", "vite"),
    ("next.config.js",  "npm run dev", "next"),
    ("next.config.ts",  "npm run dev", "next"),
    ("package.json",    "npm run dev", "node"),
    ("manage.py",       "python manage.py runserver 0.0.0.0:8000", "django"),
    ("app.py",          "python app.py", "flask"),
    ("main.py",         "python main.py", "fastapi"),
    ("Cargo.toml",      "cargo run", "rust"),
    ("go.mod",          "go run .", "go"),
]


class ServerDetector:
    @staticmethod
    def detect(workspace_path: str) -> ServerConfig | None:
        ws = Path(workspace_path)
        for detection_file, default_cmd, framework in _START_CMD_CANDIDATES:
            if (ws / detection_file).exists():
                start_cmd = default_cmd
                if detection_file == "package.json":
                    start_cmd = ServerDetector._read_npm_dev_script(ws) or default_cmd
                port = ServerDetector._detect_port(ws, framework)
                env = ServerDetector._build_env(port)
                return ServerConfig(start_cmd=start_cmd, port=port, env=env, framework=framework)
        return None

    @staticmethod
    def _read_npm_dev_script(ws: Path) -> str | None:
        try:
            data = json.loads((ws / "package.json").read_text())
            scripts = data.get("scripts", {})
            if "dev" in scripts:
                return "npm run dev"
            if scripts:
                first = next(iter(scripts))
                return f"npm run {first}"
            return None
        except Exception:
            return None

    @staticmethod
    def _detect_port(ws: Path, framework: str) -> int:
        for env_file in [".env.local", ".env", ".env.development"]:
            env_path = ws / env_file
            if env_path.exists():
                content = env_path.read_text()
                m = re.search(r"(?:^|\n)PORT\s*=\s*(\d{4,5})", content)
                if m:
                    return int(m.group(1))

        for config in ["vite.config.ts", "vite.config.js", "next.config.js", "next.config.ts"]:
            cfg_path = ws / config
            if cfg_path.exists():
                content = cfg_path.read_text()
                for pattern in _PORT_PATTERNS[1:3]:
                    m = pattern.search(content)
                    if m:
                        val = int(m.group(1))
                        if 1024 <= val <= 65535:
                            return val

        return _DEFAULT_PORTS.get(framework, 3000)

    @staticmethod
    def _build_env(port: int) -> dict[str, str]:
        env = dict(os.environ)
        env["PORT"] = str(port)
        env["CI"] = "false"
        env["BROWSER"] = "none"
        return env
