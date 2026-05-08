"""FunctionTools for UI testing — exposed to agents via ToolRegistry."""

from __future__ import annotations

from agents import function_tool


@function_tool
async def capture_screenshot(url: str, output_path: str = "/tmp/screenshot.png") -> str:
    """Capture a screenshot of the given URL. Returns path to saved PNG."""
    from packages.agent_sdk.ui_testing.screenshot_capture import ScreenshotCapture
    try:
        path = await ScreenshotCapture.capture(url, output_path)
        return f"Screenshot saved to: {path}"
    except Exception as e:
        return f"Screenshot failed: {e}"


@function_tool
def detect_dev_server(workspace: str = ".") -> str:
    """Detect the dev server start command and port for the workspace."""
    from packages.agent_sdk.ui_testing.server_detector import ServerDetector
    config = ServerDetector.detect(workspace)
    if config is None:
        return "No dev server detected."
    return f"Framework: {config.framework}, Port: {config.port}, Command: {config.start_cmd}"
