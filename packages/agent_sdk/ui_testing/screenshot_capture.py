"""Multi-strategy screenshot capture with graceful fallback cascade."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 256 * 1024  # 256KB compression cap


def _tmp_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    return path


class ScreenshotCapture:
    """
    Capture screenshots using a cascade of strategies:
    1. Playwright (async, most reliable)
    2. Chromium headless CLI
    3. Chrome CDP (google-chrome/google-chrome-stable)
    4. Chrome headless CLI
    Raises RuntimeError if all strategies fail.
    """

    @staticmethod
    async def capture(url: str, output_path: str | None = None) -> str:
        """Returns path to saved PNG. Raises RuntimeError if all strategies fail."""
        strategies = [
            ScreenshotCapture._capture_playwright,
            ScreenshotCapture._capture_chromium_headless,
            ScreenshotCapture._capture_chrome_cdp,
            ScreenshotCapture._capture_chrome_headless,
        ]
        dest = output_path or _tmp_path()
        last_error: Exception = RuntimeError("No screenshot strategy available")
        for strategy in strategies:
            try:
                result = await strategy(url, dest)
                if result and Path(result).exists():
                    return result
            except Exception as e:
                last_error = e
        raise RuntimeError(f"All screenshot strategies failed. Last: {last_error}")

    @staticmethod
    async def capture_and_compress(url: str, output_path: str | None = None) -> str:
        """Capture + downscale if larger than MAX_IMAGE_BYTES."""
        path = await ScreenshotCapture.capture(url, output_path)
        if Path(path).stat().st_size > MAX_IMAGE_BYTES:
            await asyncio.to_thread(ScreenshotCapture._downscale, path)
        return path

    @staticmethod
    def _downscale(path: str) -> None:
        try:
            from PIL import Image
            current_size = Path(path).stat().st_size
            with Image.open(path) as img:
                scale = (MAX_IMAGE_BYTES / current_size) ** 0.5
                new_size = (int(img.width * scale), int(img.height * scale))
                img.resize(new_size, Image.LANCZOS).save(path, optimize=True)
        except ImportError:
            logger.warning(
                "Pillow not installed; screenshot at %s is %d bytes (exceeds %d byte cap). "
                "Install Pillow to enable compression: pip install Pillow",
                path, Path(path).stat().st_size, MAX_IMAGE_BYTES,
            )

    @staticmethod
    async def _capture_playwright(url: str, output_path: str) -> str | None:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return None
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 800})
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await page.screenshot(path=output_path, full_page=False)
            finally:
                await browser.close()
        return output_path

    @staticmethod
    async def _capture_chromium_headless(url: str, output_path: str) -> str | None:
        binary = shutil.which("chromium") or shutil.which("chromium-browser")
        if not binary:
            return None
        return await ScreenshotCapture._run_headless_binary(binary, url, output_path)

    @staticmethod
    async def _capture_chrome_cdp(url: str, output_path: str) -> str | None:
        binary = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
        if not binary:
            return None
        return await ScreenshotCapture._run_headless_binary(binary, url, output_path)

    @staticmethod
    async def _capture_chrome_headless(url: str, output_path: str) -> str | None:
        binary = shutil.which("chrome")
        if not binary:
            return None
        return await ScreenshotCapture._run_headless_binary(binary, url, output_path)

    @staticmethod
    async def _run_headless_binary(binary: str, url: str, output_path: str) -> str | None:
        cmd = [
            binary, "--headless", "--disable-gpu",
            f"--screenshot={output_path}", "--window-size=1280,800",
            "--no-sandbox", url,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=20)
        except asyncio.TimeoutError:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
            # Remove any partial/empty file so the cascade doesn't mistake it for a valid result
            try:
                Path(output_path).unlink(missing_ok=True)
            except OSError:
                pass
            return None
        return output_path if Path(output_path).exists() else None
