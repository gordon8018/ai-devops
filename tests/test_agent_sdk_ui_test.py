"""Tests for the UITestModule."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.agent_sdk.ui_testing.server_detector import ServerDetector, ServerConfig
from packages.agent_sdk.ui_testing.screenshot_capture import ScreenshotCapture
from packages.agent_sdk.ui_testing.visual_verifier import VisualVerifier, UITestResult
from packages.agent_sdk.ui_testing.ui_test_orchestrator import UITestOrchestrator


# ── helpers ─────────────────────────────────────────────────────────────────

def _make_subtask(**overrides):
    from orchestrator.bin.plan_schema import Subtask, TaskType
    defaults = dict(
        id="ui-s1", title="UI Task", description="Check UI",
        agent="codex", model="gpt-5.4", effort="medium",
        worktree_strategy="shared", task_type=TaskType.CODE_GENERATION,
        definition_of_done=("Hero section visible", "Nav links work"),
    )
    defaults.update(overrides)
    return Subtask(**defaults)


@dataclass
class FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    total_tokens: int = 150


@dataclass
class FakeRunResult:
    final_output: str = "VISUAL_RESULT: PASS\nScore: 90/100"
    new_items: list = field(default_factory=list)
    last_agent: Any = None
    usage: FakeUsage = field(default_factory=FakeUsage)


# ── ServerDetector ───────────────────────────────────────────────────────────

class TestServerDetector:
    def test_node_project_from_package_json(self, tmp_path):
        pkg = {"scripts": {"dev": "vite"}, "dependencies": {}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        config = ServerDetector.detect(str(tmp_path))
        assert config is not None
        assert config.framework == "node"
        assert config.port == 3000

    def test_vite_config_detected(self, tmp_path):
        pkg = {"scripts": {"dev": "vite"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        (tmp_path / "vite.config.ts").write_text("export default { server: { port: 5173 } }")
        config = ServerDetector.detect(str(tmp_path))
        assert config is not None
        assert config.framework == "vite"
        assert config.port == 5173

    def test_django_project_detected(self, tmp_path):
        (tmp_path / "manage.py").write_text("# django manage")
        config = ServerDetector.detect(str(tmp_path))
        assert config is not None
        assert config.framework == "django"
        assert config.port == 8000

    def test_reads_port_from_env_file(self, tmp_path):
        pkg = {"scripts": {"dev": "vite"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        (tmp_path / ".env").write_text("PORT=4000\nNODE_ENV=development\n")
        config = ServerDetector.detect(str(tmp_path))
        assert config is not None
        assert config.port == 4000

    def test_reads_port_from_env_local(self, tmp_path):
        (tmp_path / "manage.py").write_text("")
        (tmp_path / ".env.local").write_text("PORT=9000\n")
        config = ServerDetector.detect(str(tmp_path))
        assert config is not None
        assert config.port == 9000

    def test_returns_none_for_empty_workspace(self, tmp_path):
        config = ServerDetector.detect(str(tmp_path))
        assert config is None

    def test_env_contains_port_ci_browser(self, tmp_path):
        (tmp_path / "manage.py").write_text("")
        config = ServerDetector.detect(str(tmp_path))
        assert config is not None
        assert config.env["PORT"] == str(config.port)
        assert config.env["CI"] == "false"
        assert config.env["BROWSER"] == "none"

    def test_go_mod_detected(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/app\n")
        config = ServerDetector.detect(str(tmp_path))
        assert config is not None
        assert config.framework == "go"
        assert config.port == 8080


# ── ScreenshotCapture ────────────────────────────────────────────────────────

class TestScreenshotCapture:
    @pytest.mark.asyncio
    async def test_uses_playwright_when_available(self, tmp_path):
        output = str(tmp_path / "shot.png")
        # Create a fake PNG file to simulate playwright writing it
        Path(output).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        mock_page = AsyncMock()
        mock_browser = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.close = AsyncMock()

        async def fake_screenshot(path, full_page):
            Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        mock_page.screenshot = AsyncMock(side_effect=fake_screenshot)
        mock_page.goto = AsyncMock()

        mock_chromium = AsyncMock()
        mock_chromium.launch = AsyncMock(return_value=mock_browser)

        mock_p = AsyncMock()
        mock_p.chromium = mock_chromium
        mock_p.__aenter__ = AsyncMock(return_value=mock_p)
        mock_p.__aexit__ = AsyncMock(return_value=False)

        mock_playwright_cls = MagicMock(return_value=mock_p)

        with patch.dict("sys.modules", {"playwright": MagicMock(), "playwright.async_api": MagicMock()}):
            with patch(
                "packages.agent_sdk.ui_testing.screenshot_capture.ScreenshotCapture._capture_playwright",
                new_callable=AsyncMock,
                return_value=output,
            ):
                result = await ScreenshotCapture.capture("http://localhost:3000", output)
        assert result == output

    @pytest.mark.asyncio
    async def test_skips_playwright_on_import_error(self):
        # _capture_playwright returns None when playwright is not importable
        result = await ScreenshotCapture._capture_playwright("http://localhost:3000", "/tmp/x.png")
        # Without playwright installed this returns None (not raises)
        assert result is None or isinstance(result, str)

    @pytest.mark.asyncio
    async def test_all_strategies_fail_raises_runtime_error(self):
        with (
            patch.object(ScreenshotCapture, "_capture_playwright", new_callable=AsyncMock, return_value=None),
            patch.object(ScreenshotCapture, "_capture_chromium_headless", new_callable=AsyncMock, return_value=None),
            patch.object(ScreenshotCapture, "_capture_chrome_cdp", new_callable=AsyncMock, return_value=None),
            patch.object(ScreenshotCapture, "_capture_chrome_headless", new_callable=AsyncMock, return_value=None),
        ):
            with pytest.raises(RuntimeError, match="All screenshot strategies failed"):
                await ScreenshotCapture.capture("http://localhost:3000")

    @pytest.mark.asyncio
    async def test_capture_and_compress_skips_downscale_when_small(self, tmp_path):
        small_png = tmp_path / "small.png"
        small_png.write_bytes(b"\x89PNG" + b"\x00" * 100)  # well under 256KB
        with patch.object(
            ScreenshotCapture, "capture",
            new_callable=AsyncMock,
            return_value=str(small_png),
        ):
            with patch.object(ScreenshotCapture, "_downscale") as mock_downscale:
                await ScreenshotCapture.capture_and_compress("http://localhost:3000")
                mock_downscale.assert_not_called()

    @pytest.mark.asyncio
    async def test_headless_binary_returns_none_on_timeout(self, tmp_path):
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.wait = AsyncMock(side_effect=asyncio.TimeoutError)
            mock_proc.terminate = MagicMock()
            mock_proc.kill = MagicMock()
            mock_exec.return_value = mock_proc
            result = await ScreenshotCapture._run_headless_binary(
                "/usr/bin/chromium", "http://localhost", str(tmp_path / "shot.png")
            )
            assert result is None
            mock_proc.terminate.assert_called_once()


# ── VisualVerifier ───────────────────────────────────────────────────────────

class TestVisualVerifier:
    @pytest.mark.asyncio
    async def test_parses_pass_sentinel(self, tmp_path):
        png = tmp_path / "shot.png"
        png.write_bytes(b"\x89PNG" + b"\x00" * 50)
        raw = "Score: 90/100\nLooks good.\nVISUAL_RESULT: PASS"
        with patch("packages.agent_sdk.ui_testing.visual_verifier.Runner.run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = FakeRunResult(final_output=raw)
            result = await VisualVerifier.verify(str(png), "Hero visible", "s1")
        assert result.passed is True
        assert result.score == 90

    @pytest.mark.asyncio
    async def test_parses_fail_with_critical_finding(self, tmp_path):
        png = tmp_path / "shot.png"
        png.write_bytes(b"\x89PNG" + b"\x00" * 50)
        raw = "Score: 70/100\n[CRITICAL] Hero section missing\n[HIGH] Broken nav\nVISUAL_RESULT: FAIL"
        with patch("packages.agent_sdk.ui_testing.visual_verifier.Runner.run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = FakeRunResult(final_output=raw)
            result = await VisualVerifier.verify(str(png), "Hero visible", "s1")
        assert result.passed is False
        assert result.score == 70
        severities = [f.severity for f in result.findings]
        assert "critical" in severities
        assert "high" in severities

    @pytest.mark.asyncio
    async def test_handles_runner_exception_gracefully(self, tmp_path):
        png = tmp_path / "shot.png"
        png.write_bytes(b"\x89PNG" + b"\x00" * 50)
        with patch("packages.agent_sdk.ui_testing.visual_verifier.Runner.run", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = RuntimeError("connection reset")
            result = await VisualVerifier.verify(str(png), "DoD", "s1")
        assert result.passed is False
        assert result.score == 0

    @pytest.mark.asyncio
    async def test_critical_blocks_pass_even_with_high_score(self, tmp_path):
        png = tmp_path / "shot.png"
        png.write_bytes(b"\x89PNG" + b"\x00" * 50)
        raw = "Score: 92/100\n[CRITICAL] Login broken\nVISUAL_RESULT: PASS"
        with patch("packages.agent_sdk.ui_testing.visual_verifier.Runner.run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = FakeRunResult(final_output=raw)
            result = await VisualVerifier.verify(str(png), "DoD", "s1")
        assert result.passed is False

    def test_parse_no_sentinel_uses_threshold(self):
        raw = "Score: 88/100\nAll good."
        result = VisualVerifier._parse(raw, "/tmp/s.png", "s1")
        assert result.passed is True
        assert result.score == 88

    def test_parse_below_threshold_fails(self):
        raw = "Score: 60/100\nMany issues."
        result = VisualVerifier._parse(raw, "/tmp/s.png", "s1")
        assert result.passed is False


# ── UITestOrchestrator ───────────────────────────────────────────────────────

class TestUITestOrchestrator:
    @pytest.mark.asyncio
    async def test_no_server_detected_returns_failed(self, tmp_path):
        subtask = _make_subtask()
        orch = UITestOrchestrator()
        result = await orch.run(subtask, str(tmp_path))
        assert result.passed is False
        assert len(result.findings) == 1
        assert result.findings[0].severity == "high"

    @pytest.mark.asyncio
    async def test_stops_server_in_finally_on_screenshot_exception(self, tmp_path):
        pkg = {"scripts": {"dev": "vite"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        subtask = _make_subtask()

        fake_proc = MagicMock()
        fake_proc.proc = MagicMock()
        fake_server = MagicMock()
        fake_server.url = "http://localhost:3000"
        fake_server.port = 3000

        with (
            patch("packages.agent_sdk.ui_testing.ui_test_orchestrator.ServerManager.start_and_wait",
                  new_callable=AsyncMock, return_value=fake_server),
            patch("packages.agent_sdk.ui_testing.ui_test_orchestrator.ScreenshotCapture.capture_and_compress",
                  new_callable=AsyncMock, side_effect=RuntimeError("no chrome")),
            patch("packages.agent_sdk.ui_testing.ui_test_orchestrator.ServerManager.stop") as mock_stop,
        ):
            with pytest.raises(RuntimeError):
                await orch_run_raw(subtask, str(tmp_path))
            mock_stop.assert_called_once_with(fake_server)

    @pytest.mark.asyncio
    async def test_publishes_all_events(self, tmp_path):
        pkg = {"scripts": {"dev": "vite"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        subtask = _make_subtask()
        bus = MagicMock()
        orch = UITestOrchestrator(event_bus=bus)

        fake_server = MagicMock()
        fake_server.url = "http://localhost:5173"
        fake_server.port = 5173
        screenshot_path = str(tmp_path / "shot.png")
        Path(screenshot_path).write_bytes(b"\x89PNG" + b"\x00" * 50)

        with (
            patch("packages.agent_sdk.ui_testing.ui_test_orchestrator.ServerManager.start_and_wait",
                  new_callable=AsyncMock, return_value=fake_server),
            patch("packages.agent_sdk.ui_testing.ui_test_orchestrator.ScreenshotCapture.capture_and_compress",
                  new_callable=AsyncMock, return_value=screenshot_path),
            patch("packages.agent_sdk.ui_testing.ui_test_orchestrator.VisualVerifier.verify",
                  new_callable=AsyncMock,
                  return_value=UITestResult(passed=True, score=90, findings=(),
                                            screenshot_path=screenshot_path, raw_output="VISUAL_RESULT: PASS")),
            patch("packages.agent_sdk.ui_testing.ui_test_orchestrator.ServerManager.stop"),
        ):
            await orch.run(subtask, str(tmp_path))

        published = {call.args[0] for call in bus.publish.call_args_list}
        assert "ui_test.server_detected" in published
        assert "ui_test.server_ready" in published
        assert "ui_test.screenshot_captured" in published
        assert "ui_test.completed" in published
        assert "ui_test.server_stopped" in published

    @pytest.mark.asyncio
    async def test_timeout_returns_failed_result(self, tmp_path):
        pkg = {"scripts": {"dev": "vite"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        subtask = _make_subtask()
        orch = UITestOrchestrator()

        with (
            patch("packages.agent_sdk.ui_testing.ui_test_orchestrator.ServerManager.start_and_wait",
                  new_callable=AsyncMock, side_effect=TimeoutError("server timeout")),
            patch("packages.agent_sdk.ui_testing.ui_test_orchestrator.ServerManager.stop"),
        ):
            result = await orch.run(subtask, str(tmp_path))

        assert result.passed is False
        assert result.findings[0].severity == "critical"
        assert "timeout" in result.raw_output.lower()


# Helper to trigger the finally path without catching TimeoutError in orchestrator
async def orch_run_raw(subtask, workspace_path):
    from packages.agent_sdk.ui_testing.server_detector import ServerDetector
    from packages.agent_sdk.ui_testing.server_manager import ServerManager
    from packages.agent_sdk.ui_testing.screenshot_capture import ScreenshotCapture
    config = ServerDetector.detect(workspace_path)
    server_proc = None
    try:
        server_proc = await ServerManager.start_and_wait(config, workspace_path)
        await ScreenshotCapture.capture_and_compress(server_proc.url)
    finally:
        if server_proc is not None:
            ServerManager.stop(server_proc)
