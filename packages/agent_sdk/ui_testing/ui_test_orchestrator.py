"""End-to-end UI test: detect → start → screenshot → verify → stop."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from packages.agent_sdk.ui_testing.server_detector import ServerDetector
from packages.agent_sdk.ui_testing.server_manager import ServerManager
from packages.agent_sdk.ui_testing.screenshot_capture import ScreenshotCapture
from packages.agent_sdk.ui_testing.visual_verifier import VisualVerifier, UITestResult
from packages.shared.domain.models import ReviewFinding

if TYPE_CHECKING:
    from orchestrator.bin.plan_schema import Subtask

logger = logging.getLogger(__name__)


class UITestOrchestrator:
    def __init__(self, event_bus: Any = None, verifier_model: str = "claude-opus-4-6"):
        self._event_bus = event_bus
        self._verifier_model = verifier_model

    def _publish(self, event_type: str, payload: dict) -> None:
        if self._event_bus is not None:
            self._event_bus.publish(event_type, payload)

    async def run(self, subtask: Subtask, workspace_path: str) -> UITestResult:
        config = ServerDetector.detect(workspace_path)
        if config is None:
            return UITestResult(
                passed=False,
                score=0,
                findings=(ReviewFinding(
                    finding_id=f"{subtask.id}-ui-no-server",
                    category="ui_test",
                    severity="high",
                    message=(
                        "No dev server detected in workspace. "
                        "Add package.json, manage.py, or equivalent."
                    ),
                    source_guardrail="UITestOrchestrator",
                ),),
                screenshot_path="",
                raw_output="Server detection failed.",
            )

        self._publish("ui_test.server_detected", {
            "subtask_id": subtask.id,
            "framework": config.framework,
            "port": config.port,
            "cmd": config.start_cmd,
        })

        server_proc = None
        try:
            server_proc = await ServerManager.start_and_wait(config, workspace_path)
            self._publish("ui_test.server_ready", {
                "subtask_id": subtask.id,
                "url": server_proc.url,
            })

            screenshot_path = await ScreenshotCapture.capture_and_compress(server_proc.url)
            self._publish("ui_test.screenshot_captured", {
                "subtask_id": subtask.id,
                "path": screenshot_path,
            })

            definition_of_done = (
                "\n".join(subtask.definition_of_done)
                if subtask.definition_of_done
                else ""
            )
            result = await VisualVerifier.verify(
                screenshot_path=screenshot_path,
                definition_of_done=definition_of_done,
                subtask_id=subtask.id,
                model=self._verifier_model,
            )

            self._publish("ui_test.completed", {
                "subtask_id": subtask.id,
                "passed": result.passed,
                "score": result.score,
            })
            return result

        except TimeoutError as e:
            return UITestResult(
                passed=False,
                score=0,
                findings=(ReviewFinding(
                    finding_id=f"{subtask.id}-ui-timeout",
                    category="ui_test",
                    severity="critical",
                    message=str(e),
                    source_guardrail="UITestOrchestrator",
                ),),
                screenshot_path="",
                raw_output=str(e),
            )
        finally:
            if server_proc is not None:
                ServerManager.stop(server_proc)
                self._publish("ui_test.server_stopped", {"subtask_id": subtask.id})
