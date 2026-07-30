"""Authenticated host service exposing an allowlisted Dreamina CLI surface."""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import hmac
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Operation = Literal[
    "text2image", "image2image", "text2video", "image2video", "frames2video"
]
ImageRatio = Literal["21:9", "16:9", "3:2", "4:3", "1:1", "3:4", "2:3", "9:16"]
ImageModel = Literal["3.0", "3.1", "4.0", "4.1", "4.5", "4.6", "4.7", "5.0"]
VideoModel = Literal[
    "seedance1.0fast",
    "seedance1.0",
    "seedance1.5pro",
    "seedance2.0",
    "seedance2.0fast",
    "seedance2.0_vip",
    "seedance2.0fast_vip",
    "seedance2.0mini",
]
_SUBMIT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{5,127}$")
_MEDIA_EXTENSIONS = {
    "image": {".png", ".jpg", ".jpeg", ".webp"},
    "video": {".mp4", ".mov", ".webm"},
}


class EncodedImage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    filename: str = "image.png"
    content_base64: str = Field(alias="contentBase64", max_length=30_000_000)

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        name = Path(value).name
        if name != value or not name or Path(name).suffix.lower() not in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
        }:
            raise ValueError("unsupported image filename")
        return name


class DreaminaTaskRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    operation: Operation
    prompt: str = Field(min_length=1, max_length=20_000)
    ratio: ImageRatio = "1:1"
    image_model: ImageModel = Field(default="5.0", alias="imageModel")
    image_resolution: Literal["1k", "2k", "4k"] = Field(
        default="2k", alias="imageResolution"
    )
    video_model: VideoModel = Field(default="seedance2.0fast", alias="videoModel")
    video_resolution: Literal["720p", "1080p", "4k"] = Field(
        default="720p", alias="videoResolution"
    )
    duration: int = Field(default=5, ge=3, le=15)
    images: list[EncodedImage] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_operation_images(self) -> "DreaminaTaskRequest":
        expected = {
            "text2image": 0,
            "image2image": range(1, 11),
            "text2video": 0,
            "image2video": 1,
            "frames2video": 2,
        }[self.operation]
        count = len(self.images)
        if isinstance(expected, range):
            valid = count in expected
        else:
            valid = count == expected
        if not valid:
            raise ValueError(f"invalid image count for {self.operation}")
        if self.operation == "image2image" and self.image_model in {"3.0", "3.1"}:
            raise ValueError("image2image requires Seedream 4.0 or newer")
        if self.image_model in {"3.0", "3.1"} and self.image_resolution == "4k":
            raise ValueError("Seedream 3.x does not support 4k")
        if self.image_model not in {"3.0", "3.1"} and self.image_resolution == "1k":
            raise ValueError("Seedream 4.x and 5.0 do not support 1k")
        seedance_1x = {"seedance1.0fast", "seedance1.0"}
        seedance_2x = {
            "seedance2.0",
            "seedance2.0fast",
            "seedance2.0_vip",
            "seedance2.0fast_vip",
            "seedance2.0mini",
        }
        if self.operation == "text2video" and self.video_model not in seedance_2x:
            raise ValueError("text2video requires a Seedance 2.0 model")
        if self.operation == "frames2video" and self.video_model in seedance_1x:
            raise ValueError("frames2video does not support Seedance 1.0")
        if self.operation == "text2video" and self.ratio in {"3:2", "2:3"}:
            raise ValueError("unsupported text2video ratio")
        if self.operation in {"text2video", "image2video", "frames2video"}:
            minimum, maximum = (3, 10) if self.video_model in seedance_1x else (4, 15)
            if self.video_model == "seedance1.5pro":
                maximum = 12
            if not minimum <= self.duration <= maximum:
                raise ValueError(
                    f"{self.video_model} duration must be between {minimum} and {maximum} seconds"
                )
        if self.video_resolution != "720p" and self.video_model != "seedance2.0_vip":
            raise ValueError("only seedance2.0_vip supports 1080p/4k")
        return self


class LoginCheckRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    device_code: str = Field(alias="deviceCode", min_length=8, max_length=512)


def _write_images(images: list[EncodedImage], directory: Path) -> list[Path]:
    paths: list[Path] = []
    for index, image in enumerate(images):
        try:
            content = base64.b64decode(image.content_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("invalid image base64") from exc
        if not content:
            raise ValueError("empty image")
        target = directory / f"{index:02d}_{image.filename}"
        target.write_bytes(content)
        paths.append(target)
    return paths


def build_submit_command(payload: DreaminaTaskRequest, work_dir: Path) -> list[str]:
    paths = _write_images(payload.images, work_dir)
    command = [payload.operation, f"--prompt={payload.prompt}"]
    if payload.operation in {"text2image", "image2image"}:
        if paths:
            command.append(f"--images={','.join(str(path) for path in paths)}")
        command.extend(
            [
                f"--ratio={payload.ratio}",
                f"--resolution_type={payload.image_resolution}",
                f"--model_version={payload.image_model}",
                "--generate_num=1",
            ]
        )
    else:
        if payload.operation == "image2video":
            command.append(f"--image={paths[0]}")
        elif payload.operation == "frames2video":
            command.extend([f"--first={paths[0]}", f"--last={paths[1]}"])
        elif payload.operation == "text2video":
            command.append(f"--ratio={payload.ratio}")
        command.extend(
            [
                f"--duration={payload.duration}",
                f"--video_resolution={payload.video_resolution}",
                f"--model_version={payload.video_model}",
            ]
        )
    command.append("--poll=0")
    return command


def _json_output(stdout: str) -> Any:
    text = stdout.strip()
    if not text:
        raise RuntimeError("Dreamina CLI returned no output")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Dreamina CLI returned invalid JSON: {text[-500:]}") from exc


class DreaminaCli:
    def __init__(self, binary: str):
        resolved = shutil.which(binary) if os.sep not in binary else binary
        if not resolved or not Path(resolved).is_file():
            raise RuntimeError(f"dreamina CLI not found: {binary}")
        self.binary = str(resolved)

    async def run(self, *args: str, timeout: float = 120.0) -> Any:
        process = await asyncio.create_subprocess_exec(
            self.binary,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError("Dreamina CLI command timed out") from None
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            raise RuntimeError(stderr_text or stdout_text.strip() or "Dreamina CLI failed")
        return _json_output(stdout_text)


def create_bridge_app(
    *,
    token: str | None = None,
    cli_binary: str | None = None,
    data_dir: Path | None = None,
) -> FastAPI:
    bridge_token = token or os.environ.get("DREAMINA_BRIDGE_TOKEN", "").strip()
    if len(bridge_token) < 32:
        raise RuntimeError("DREAMINA_BRIDGE_TOKEN must contain at least 32 characters")
    cli = DreaminaCli(cli_binary or os.environ.get("DREAMINA_CLI_PATH", "dreamina"))
    root = data_dir or Path(
        os.environ.get("DREAMINA_BRIDGE_DATA_DIR", "~/.dreamina_bridge")
    ).expanduser()
    downloads = root / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="DramaClaw Dreamina Host Bridge", docs_url=None, redoc_url=None)

    def authenticate(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        supplied = ""
        if authorization and authorization.startswith("Bearer "):
            supplied = authorization.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(supplied, bridge_token):
            raise HTTPException(status_code=401, detail="invalid bridge token")

    async def account_status() -> dict[str, Any]:
        try:
            credit = await cli.run("user_credit", timeout=30)
        except RuntimeError as exc:
            return {
                "configured": True,
                "reachable": True,
                "loggedIn": False,
                "error": str(exc),
            }
        return {
            "configured": True,
            "reachable": True,
            "loggedIn": True,
            "account": {
                "totalCredit": credit.get("total_credit"),
                "userId": str(credit.get("user_id") or ""),
                "userName": str(credit.get("user_name") or ""),
                "vipLevel": str(credit.get("vip_level") or ""),
            },
        }

    @app.get("/v1/status", dependencies=[Depends(authenticate)])
    async def status() -> dict[str, Any]:
        return await account_status()

    @app.post("/v1/login/start", dependencies=[Depends(authenticate)])
    async def login_start() -> dict[str, Any]:
        status_data = await account_status()
        if status_data["loggedIn"]:
            return {**status_data, "reused": True}
        result = await cli.run("login", "--headless", timeout=30)
        return {
            "loggedIn": False,
            "reused": False,
            "verificationUri": result.get("verification_uri"),
            "userCode": result.get("user_code"),
            "deviceCode": result.get("device_code"),
        }

    @app.post("/v1/login/check", dependencies=[Depends(authenticate)])
    async def login_check(body: LoginCheckRequest) -> dict[str, Any]:
        await cli.run(
            "login",
            "checklogin",
            f"--device_code={body.device_code}",
            "--poll=0",
            timeout=30,
        )
        return await account_status()

    @app.post("/v1/logout", dependencies=[Depends(authenticate)])
    async def logout() -> dict[str, Any]:
        await cli.run("logout", timeout=30)
        return {"configured": True, "reachable": True, "loggedIn": False}

    @app.post("/v1/tasks", dependencies=[Depends(authenticate)])
    async def submit_task(body: DreaminaTaskRequest) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="dreamina-bridge-") as temp_dir:
            command = build_submit_command(body, Path(temp_dir))
            result = await cli.run(*command, timeout=300)
        if not isinstance(result, dict):
            raise HTTPException(status_code=502, detail="invalid Dreamina submit response")
        if not result.get("submit_id"):
            raise HTTPException(status_code=502, detail="Dreamina did not return submit_id")
        return result

    def validated_submit_id(submit_id: str) -> str:
        if not _SUBMIT_ID_RE.fullmatch(submit_id):
            raise HTTPException(status_code=400, detail="invalid submit_id")
        return submit_id

    @app.get("/v1/tasks/{submit_id}", dependencies=[Depends(authenticate)])
    async def query_task(submit_id: str) -> dict[str, Any]:
        return await cli.run(
            "query_result", f"--submit_id={validated_submit_id(submit_id)}", timeout=60
        )

    @app.get("/v1/tasks/{submit_id}/download", dependencies=[Depends(authenticate)])
    async def download_task(
        submit_id: str,
        kind: Literal["image", "video"] = Query(),
    ) -> FileResponse:
        task_id = validated_submit_id(submit_id)
        target_dir = downloads / task_id
        target_dir.mkdir(parents=True, exist_ok=True)
        candidates = [
            path
            for path in target_dir.iterdir()
            if path.is_file() and path.suffix.lower() in _MEDIA_EXTENSIONS[kind]
        ]
        if not candidates:
            await cli.run(
                "query_result",
                f"--submit_id={task_id}",
                f"--download_dir={target_dir}",
                timeout=600,
            )
            candidates = [
                path
                for path in target_dir.rglob("*")
                if path.is_file() and path.suffix.lower() in _MEDIA_EXTENSIONS[kind]
            ]
        if not candidates:
            raise HTTPException(status_code=502, detail=f"Dreamina returned no {kind} file")
        selected = max(candidates, key=lambda path: path.stat().st_mtime)
        return FileResponse(selected, filename=selected.name)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Dreamina CLI bridge")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(create_bridge_app(), host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
