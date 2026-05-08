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


@dataclass
class ServerProcess:
    proc: subprocess.Popen
    port: int
    url: str


class ServerManager:
    @staticmethod
    async def start_and_wait(config: ServerConfig, workspace_path: str) -> ServerProcess:
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
        while time.monotonic() < deadline:
            if ServerManager._port_open("localhost", config.port):
                return ServerProcess(proc=proc, port=config.port, url=url)
            await asyncio.sleep(POLL_INTERVAL_S)
        proc.terminate()
        raise TimeoutError(
            f"Dev server did not start on port {config.port} within {READINESS_TIMEOUT_S}s. "
            f"Command: {config.start_cmd}"
        )

    @staticmethod
    def stop(server_proc: ServerProcess) -> None:
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

    @staticmethod
    def _port_open(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            return False
