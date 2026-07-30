"""Client for the authenticated Dreamina CLI host bridge."""

from __future__ import annotations

import asyncio
import base64
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


@dataclass(frozen=True)
class DreaminaBridgeConfig:
    base_url: str
    token: str
    poll_interval_seconds: float = 3.0
    task_timeout_seconds: float = 1800.0

    @classmethod
    def from_env(cls) -> "DreaminaBridgeConfig":
        return cls(
            base_url=os.environ.get("DREAMINA_BRIDGE_URL", "").strip().rstrip("/"),
            token=os.environ.get("DREAMINA_BRIDGE_TOKEN", "").strip(),
            poll_interval_seconds=float(
                os.environ.get("DREAMINA_BRIDGE_POLL_INTERVAL_SECONDS", "3")
            ),
            task_timeout_seconds=float(
                os.environ.get("DREAMINA_BRIDGE_TASK_TIMEOUT_SECONDS", "1800")
            ),
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url and len(self.token) >= 32)


class DreaminaBridgeClient:
    def __init__(self, config: DreaminaBridgeConfig | None = None):
        self.config = config or DreaminaBridgeConfig.from_env()
        if not self.config.configured:
            raise ValueError("DREAMINA_BRIDGE_URL and DREAMINA_BRIDGE_TOKEN must be configured")

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.token}"}

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method,
                f"{self.config.base_url}{path}",
                headers=self._headers,
                json=payload,
            )
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except Exception:
                detail = response.text
            raise RuntimeError(f"Dreamina bridge error: {detail or response.status_code}")
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Dreamina bridge returned an invalid response")
        return data

    async def _request_bytes(self, path: str) -> bytes:
        timeout = max(60.0, self.config.task_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{self.config.base_url}{path}", headers=self._headers
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Dreamina bridge download failed: {response.text}")
        return response.content

    async def status(self) -> dict[str, Any]:
        return await self._request_json("GET", "/v1/status", timeout=5.0)

    async def start_login(self) -> dict[str, Any]:
        return await self._request_json("POST", "/v1/login/start")

    async def check_login(self, device_code: str) -> dict[str, Any]:
        return await self._request_json(
            "POST", "/v1/login/check", payload={"deviceCode": device_code}
        )

    async def logout(self) -> dict[str, Any]:
        return await self._request_json("POST", "/v1/logout")

    @staticmethod
    def _encoded_images(paths: list[str] | None) -> list[dict[str, str]]:
        if len(paths or []) > 10:
            raise ValueError("Dreamina accepts at most 10 reference images")
        images: list[dict[str, str]] = []
        for raw_path in paths or []:
            path = Path(raw_path)
            if not path.is_file():
                raise FileNotFoundError(f"Dreamina reference image not found: {path}")
            images.append(
                {
                    "filename": path.name,
                    "contentBase64": base64.b64encode(path.read_bytes()).decode("ascii"),
                }
            )
        return images

    async def _submit_and_wait(
        self, payload: dict[str, Any], *, media_kind: str
    ) -> tuple[bytes, str]:
        submitted = await self._request_json("POST", "/v1/tasks", payload=payload)
        submit_id = str(submitted.get("submit_id") or "").strip()
        status = str(submitted.get("gen_status") or "").strip().lower()
        if not submit_id:
            raise RuntimeError("Dreamina did not return submit_id")
        deadline = time.monotonic() + self.config.task_timeout_seconds
        result = submitted
        while status not in {"success", "fail", "failed"}:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Dreamina task timed out: {submit_id}")
            await asyncio.sleep(max(0, self.config.poll_interval_seconds))
            result = await self._request_json(
                "GET", f"/v1/tasks/{quote(submit_id, safe='')}"
            )
            status = str(result.get("gen_status") or "").strip().lower()
        if status != "success":
            reason = str(result.get("fail_reason") or "Dreamina generation failed")
            raise RuntimeError(reason)
        media = await self._request_bytes(
            f"/v1/tasks/{quote(submit_id, safe='')}/download?kind={media_kind}"
        )
        return media, submit_id

    async def generate_image(
        self,
        *,
        prompt: str,
        ratio: str,
        image_paths: list[str] | None = None,
        model: str = "5.0",
        resolution: str = "2k",
    ) -> bytes:
        images = self._encoded_images(image_paths)
        media, _ = await self._submit_and_wait(
            {
                "operation": "image2image" if images else "text2image",
                "prompt": prompt,
                "ratio": ratio,
                "imageModel": model,
                "imageResolution": resolution,
                "images": images,
            },
            media_kind="image",
        )
        return media

    async def generate_video(
        self,
        *,
        prompt: str,
        ratio: str,
        duration: int,
        image_path: str | None = None,
        last_frame_path: str | None = None,
        model: str = "seedance2.0fast",
        resolution: str = "720p",
    ) -> tuple[bytes, str]:
        if last_frame_path and not image_path:
            raise ValueError("Dreamina last-frame generation requires a first image")
        images = self._encoded_images(
            [path for path in (image_path, last_frame_path) if path]
        )
        if len(images) == 2:
            operation = "frames2video"
        elif len(images) == 1:
            operation = "image2video"
        else:
            operation = "text2video"
        return await self._submit_and_wait(
            {
                "operation": operation,
                "prompt": prompt,
                "ratio": ratio,
                "duration": duration,
                "videoModel": model,
                "videoResolution": resolution,
                "images": images,
            },
            media_kind="video",
        )


def dreamina_bridge_status_stub(error: str = "") -> dict[str, Any]:
    config = DreaminaBridgeConfig.from_env()
    return {
        "configured": config.configured,
        "reachable": False,
        "loggedIn": False,
        "error": error,
    }
