from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_dreamina_image_selection_uses_subscription_bridge(monkeypatch) -> None:
    monkeypatch.setenv("DREAMINA_BRIDGE_URL", "http://host.docker.internal:8791")
    monkeypatch.setenv("DREAMINA_BRIDGE_TOKEN", "t" * 32)

    import novelvideo.config as config

    assert config.image_generation_selection_options()["dreamina_subscription"] == (
        "即梦订阅账号（Seedream 5.0）"
    )
    image_config = config.get_grid_generation_config(
        selection_override="dreamina_subscription"
    )

    assert image_config["provider"] == "dreamina"
    assert image_config["api_key"] == "t" * 32
    assert image_config["base_url"] == "http://host.docker.internal:8791"
    assert image_config["model"] == "5.0"


def test_dreamina_image_selection_is_hidden_without_bridge(monkeypatch) -> None:
    import novelvideo.config as config

    monkeypatch.delenv("DREAMINA_BRIDGE_URL", raising=False)
    monkeypatch.delenv("DREAMINA_BRIDGE_TOKEN", raising=False)
    monkeypatch.setattr(config, "DREAMINA_BRIDGE_URL", "")
    monkeypatch.setattr(config, "DREAMINA_BRIDGE_TOKEN", "")

    assert "dreamina_subscription" not in config.image_generation_selection_options()


def test_dreamina_video_backend_creates_subscription_generator(monkeypatch) -> None:
    monkeypatch.setenv("DREAMINA_BRIDGE_URL", "http://host.docker.internal:8791")
    monkeypatch.setenv("DREAMINA_BRIDGE_TOKEN", "t" * 32)

    from novelvideo.generators.video_generator import (
        DreaminaSubscriptionVideoGenerator,
        create_video_generator,
    )

    generator = create_video_generator(backend="dreamina_seedance2.0fast")

    assert isinstance(generator, DreaminaSubscriptionVideoGenerator)
    assert generator.model == "seedance2.0fast"


def test_host_bridge_builds_allowlisted_image_command(tmp_path: Path) -> None:
    from novelvideo.dreamina_host_bridge import DreaminaTaskRequest, build_submit_command

    payload = DreaminaTaskRequest(
        operation="image2image",
        prompt="watercolor --version $(whoami)",
        ratio="2:3",
        image_resolution="2k",
        image_model="5.0",
        images=[
            {
                "filename": "reference.png",
                "contentBase64": base64.b64encode(b"image-bytes").decode(),
            }
        ],
    )

    command = build_submit_command(payload, tmp_path)

    assert command[:2] == ["image2image", "--prompt=watercolor --version $(whoami)"]
    assert "--ratio=2:3" in command
    assert "--resolution_type=2k" in command
    assert "--model_version=5.0" in command
    image_arg = next(item for item in command if item.startswith("--images="))
    image_path = Path(image_arg.removeprefix("--images="))
    assert image_path.parent == tmp_path
    assert image_path.read_bytes() == b"image-bytes"
    assert command[-1] == "--poll=0"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("operation", "shell"),
        ("ratio", "2:3;touch /tmp/pwned"),
        ("image_model", "5.0 --help"),
        ("video_model", "seedance2.0fast;id"),
    ],
)
def test_host_bridge_rejects_unsupported_cli_values(field: str, value: str) -> None:
    from pydantic import ValidationError

    from novelvideo.dreamina_host_bridge import DreaminaTaskRequest

    kwargs = {"operation": "text2image", "prompt": "safe prompt", field: value}

    with pytest.raises(ValidationError):
        DreaminaTaskRequest(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "operation": "image2image",
            "image_model": "3.1",
            "images": [
                {
                    "filename": "reference.png",
                    "contentBase64": base64.b64encode(b"image").decode(),
                }
            ],
        },
        {"operation": "text2image", "image_model": "5.0", "image_resolution": "1k"},
        {"operation": "text2video", "video_model": "seedance1.0", "duration": 5},
        {"operation": "text2video", "video_model": "seedance2.0fast", "duration": 3},
        {"operation": "text2video", "video_model": "seedance2.0fast", "ratio": "2:3"},
    ],
)
def test_host_bridge_rejects_unsupported_model_combinations(kwargs: dict) -> None:
    from pydantic import ValidationError

    from novelvideo.dreamina_host_bridge import DreaminaTaskRequest

    with pytest.raises(ValidationError):
        DreaminaTaskRequest(prompt="safe prompt", **kwargs)


def test_host_bridge_requires_bearer_token(monkeypatch, tmp_path: Path) -> None:
    from novelvideo import dreamina_host_bridge

    monkeypatch.setattr(
        dreamina_host_bridge.DreaminaCli,
        "__init__",
        lambda self, binary: setattr(self, "binary", binary),
    )
    app = dreamina_host_bridge.create_bridge_app(
        token="t" * 32,
        cli_binary="dreamina",
        data_dir=tmp_path,
    )
    client = TestClient(app)

    assert client.get("/v1/status").status_code == 401
    assert (
        client.get(
            "/v1/status", headers={"Authorization": f"Bearer {'x' * 32}"}
        ).status_code
        == 401
    )


def test_host_bridge_logout_keeps_bridge_connection_status(
    monkeypatch, tmp_path: Path
) -> None:
    from novelvideo import dreamina_host_bridge

    monkeypatch.setattr(
        dreamina_host_bridge.DreaminaCli,
        "__init__",
        lambda self, binary: setattr(self, "binary", binary),
    )

    async def fake_run(self, *args, timeout=120):
        assert args == ("logout",)
        return {}

    monkeypatch.setattr(dreamina_host_bridge.DreaminaCli, "run", fake_run)
    app = dreamina_host_bridge.create_bridge_app(
        token="t" * 32,
        cli_binary="dreamina",
        data_dir=tmp_path,
    )
    client = TestClient(app)

    response = client.post(
        "/v1/logout", headers={"Authorization": f"Bearer {'t' * 32}"}
    )

    assert response.json() == {
        "configured": True,
        "reachable": True,
        "loggedIn": False,
    }


def test_host_bridge_rejects_path_like_submit_ids(monkeypatch, tmp_path: Path) -> None:
    from novelvideo import dreamina_host_bridge

    monkeypatch.setattr(
        dreamina_host_bridge.DreaminaCli,
        "__init__",
        lambda self, binary: setattr(self, "binary", binary),
    )
    app = dreamina_host_bridge.create_bridge_app(
        token="t" * 32,
        cli_binary="dreamina",
        data_dir=tmp_path,
    )
    client = TestClient(app)

    response = client.get(
        "/v1/tasks/%2E%2E%2Fetc%2Fpasswd",
        headers={"Authorization": f"Bearer {'t' * 32}"},
    )

    assert response.status_code in {400, 404}


@pytest.mark.asyncio
async def test_bridge_client_polls_and_downloads_completed_image(monkeypatch) -> None:
    from novelvideo.dreamina_bridge import DreaminaBridgeClient, DreaminaBridgeConfig

    client = DreaminaBridgeClient(
        DreaminaBridgeConfig(
            base_url="http://bridge.test",
            token="t" * 32,
            poll_interval_seconds=0,
            task_timeout_seconds=30,
        )
    )
    calls: list[tuple[str, str]] = []

    async def fake_json(method: str, path: str, *, payload=None):
        calls.append((method, path))
        if path == "/v1/tasks":
            assert payload["operation"] == "text2image"
            return {"submit_id": "submit-123", "gen_status": "querying"}
        return {
            "submit_id": "submit-123",
            "gen_status": "success",
            "result_json": {"images": [{"width": 1024, "height": 1536}]},
        }

    async def fake_bytes(path: str):
        calls.append(("GET", path))
        return b"generated-image"

    monkeypatch.setattr(client, "_request_json", fake_json)
    monkeypatch.setattr(client, "_request_bytes", fake_bytes)

    result = await client.generate_image(prompt="portrait", ratio="2:3")

    assert result == b"generated-image"
    assert calls[-1] == ("GET", "/v1/tasks/submit-123/download?kind=image")


@pytest.mark.asyncio
async def test_bridge_client_video_returns_submit_id_and_rejects_missing_reference(
    monkeypatch, tmp_path: Path
) -> None:
    from novelvideo.dreamina_bridge import DreaminaBridgeClient, DreaminaBridgeConfig

    client = DreaminaBridgeClient(
        DreaminaBridgeConfig(base_url="http://bridge.test", token="t" * 32)
    )

    async def fake_submit(payload, *, media_kind):
        assert payload["operation"] == "image2video"
        assert media_kind == "video"
        return b"generated-video", "submit-video-123"

    monkeypatch.setattr(client, "_submit_and_wait", fake_submit)
    image_path = tmp_path / "first.png"
    image_path.write_bytes(b"image")

    result = await client.generate_video(
        prompt="animate",
        ratio="9:16",
        duration=5,
        image_path=str(image_path),
    )

    assert result == (b"generated-video", "submit-video-123")
    with pytest.raises(ValueError, match="requires a first image"):
        await client.generate_video(
            prompt="animate",
            ratio="9:16",
            duration=5,
            last_frame_path=str(image_path),
        )


@pytest.mark.asyncio
async def test_bridge_client_surfaces_provider_failure(monkeypatch) -> None:
    from novelvideo.dreamina_bridge import DreaminaBridgeClient, DreaminaBridgeConfig

    client = DreaminaBridgeClient(
        DreaminaBridgeConfig(
            base_url="http://bridge.test",
            token="t" * 32,
            poll_interval_seconds=0,
            task_timeout_seconds=30,
        )
    )

    async def fake_json(method: str, path: str, *, payload=None):
        if path == "/v1/tasks":
            return {"submit_id": "submit-456", "gen_status": "querying"}
        return {
            "submit_id": "submit-456",
            "gen_status": "fail",
            "fail_reason": "AigcComplianceConfirmationRequired",
        }

    monkeypatch.setattr(client, "_request_json", fake_json)

    with pytest.raises(RuntimeError, match="AigcComplianceConfirmationRequired"):
        await client.generate_image(prompt="portrait", ratio="2:3")


@pytest.mark.asyncio
async def test_dreamina_character_generation_routes_plain_and_reference_images(
    monkeypatch, tmp_path: Path
) -> None:
    from novelvideo.generators import nanobanana_character

    calls: list[dict] = []

    async def fake_dreamina_call(**kwargs):
        calls.append(kwargs)
        return b"dreamina-image", "", ""

    monkeypatch.setattr(
        nanobanana_character,
        "_call_dreamina_image_bridge",
        fake_dreamina_call,
    )
    generator = nanobanana_character.NanoBananaCharacterGenerator(
        config={
            "provider": "dreamina",
            "api_key": "t" * 32,
            "model": "5.0",
            "base_url": "http://bridge.test",
        }
    )

    plain = await generator._generate_single_image(
        client=None,
        prompt="plain portrait",
        output_path=str(tmp_path / "plain.png"),
    )
    referenced = await generator._generate_with_reference(
        client=None,
        prompt="referenced portrait",
        reference_image=None,
        output_path=str(tmp_path / "referenced.png"),
        reference_image_bytes=b"portrait-bytes",
        reference_image_name="portrait.jpg",
        additional_image_bytes=[b"costume-bytes"],
        additional_image_names=["costume.png"],
    )

    assert plain == b"dreamina-image"
    assert referenced == b"dreamina-image"
    assert calls[0]["reference_images"] is None
    assert calls[1]["reference_images"] == [
        ("portrait.jpg", b"portrait-bytes", "image/jpeg"),
        ("costume.png", b"costume-bytes", "image/png"),
    ]


def test_dreamina_gateway_routes_proxy_login_without_exposing_token(
    monkeypatch,
) -> None:
    from fastapi import FastAPI
    from novelvideo.api.routes import model_gateway

    calls: list[tuple[str, str]] = []
    monkeypatch.setenv("DREAMINA_BRIDGE_URL", "http://bridge.test")
    monkeypatch.setenv("DREAMINA_BRIDGE_TOKEN", "t" * 32)

    class FakeBridgeClient:
        async def status(self):
            calls.append(("status", ""))
            return {"configured": True, "reachable": True, "loggedIn": False}

        async def start_login(self):
            calls.append(("start", ""))
            return {
                "loggedIn": False,
                "verificationUri": "https://example.test/activate",
                "userCode": "ABCD-EFGH",
                "deviceCode": "device-code-123",
            }

        async def check_login(self, device_code: str):
            calls.append(("check", device_code))
            return {
                "configured": True,
                "reachable": True,
                "loggedIn": True,
                "account": {"vipLevel": "maestro", "totalCredit": 100},
            }

        async def logout(self):
            calls.append(("logout", ""))
            return {"loggedIn": False}

    monkeypatch.setattr(model_gateway, "DreaminaBridgeClient", FakeBridgeClient)
    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    config_response = client.get("/model-gateway/config")
    start_response = client.post("/model-gateway/dreamina/login/start")
    check_response = client.post(
        "/model-gateway/dreamina/login/check",
        json={"deviceCode": "device-code-123"},
    )
    logout_response = client.post("/model-gateway/dreamina/logout")

    assert config_response.json()["data"]["dreaminaSubscription"]["reachable"] is True
    assert start_response.json()["data"]["userCode"] == "ABCD-EFGH"
    assert check_response.json()["data"]["loggedIn"] is True
    assert logout_response.json()["data"]["loggedIn"] is False
    assert calls == [
        ("status", ""),
        ("start", ""),
        ("check", "device-code-123"),
        ("logout", ""),
    ]
    combined = "".join(
        response.text
        for response in (
            config_response,
            start_response,
            check_response,
            logout_response,
        )
    )
    assert "DREAMINA_BRIDGE_TOKEN" not in combined
