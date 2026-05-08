"""Start dev server, wait for readiness, stop cleanly."""

from __future__ import annotations

import asyncio
import shlex
import socket
import subprocess
import time
from dataclasses import dataclass

from packages.agent_sdk.ui_testing.server_detector import ServerConfig

READINESS_TIMEOUT_S = 60
POLL_INTERVAL_S = 1.0

_ALLOWED_CMD_PREFIXES = (
    "npm run ", "npm start", "yarn ", "pnpm ",
    "python ", "python3 ", "uvicorn ", "gunicorn ",
    "cargo run", "go run ", "node ", "deno run ",
)


def _validate_start_cmd(cmd: str) -> None:
    """Reject commands not matching known-safe dev-server prefixes."""
    stripped = cmd.strip()
    if not any(stripped.startswith(p) for p in _ALLOWED_CMD_PREFIXES):
        raise ValueError(f"Rejected untrusted start command: {cmd!r}")


def _stop_sync(server_proc: ServerProcess) -> None:
    try:
        server_proc.proc.terminate()
        server_proc.proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server_proc.proc.kill()
        try:
            server_proc.proc.wait(timeout=2)
        except Exception:
            pass
    except Exception:
        pass


@dataclass
class ServerProcess:
    proc: subprocess.Popen
    port: int
    url: str


class ServerManager:
    @staticmethod
    async def start_and_wait(config: ServerConfig, workspace_path: str) -> ServerProcess:
        _validate_start_cmd(config.start_cmd)
        cmd = shlex.split(config.start_cmd)
        proc = subprocess.Popen(
            cmd,
            cwd=workspace_path,
            env=config.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        url = f"http://localhost:{config.port}"
        deadline = time.monotonic() + READINESS_TIMEOUT_S
        try:
            while time.monotonic() < deadline:
                if ServerManager._port_open("localhost", config.port):
                    return ServerProcess(proc=proc, port=config.port, url=url)
                await asyncio.sleep(POLL_INTERVAL_S)
        except BaseException:
            # CancelledError or KeyboardInterrupt — kill the child before propagating
            proc.terminate()
            raise
        proc.terminate()
        raise TimeoutError(
            f"Dev server did not start on port {config.port} within {READINESS_TIMEOUT_S}s. "
            f"Command: {config.start_cmd}"
        )

    @staticmethod
    async def stop(server_proc: ServerProcess) -> None:
        """Terminate the dev server without blocking the event loop."""
        await asyncio.to_thread(_stop_sync, server_proc)

    @staticmethod
    def _port_open(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            return False
