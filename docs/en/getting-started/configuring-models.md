<!-- lang-switch -->
**English** · [简体中文](../../zh/getting-started/configuring-models.md)

# Configuring Model Providers

> Configure the official RelayClaw channel or the local NewAPI bundled with CE.

DramaClaw CE connects text, image, video, audio, and embedding models through an OpenAI-compatible NewAPI gateway. The optional Dreamina subscription channel is a separate media backend that uses the official Dreamina CLI instead of NewAPI. NewAPI channel selection, gateway address, and runtime token are saved from the web UI to local `settings.db`.

## Dreamina subscription account (optional, macOS host)

If you already have a Dreamina membership, DramaClaw can use its subscription credits for Seedream 5.0 images and Seedance 2.0 Fast videos. The official `dreamina` CLI runs on macOS, while the API normally runs in Linux Docker, so start the authenticated host bridge first:

```bash
# Generate a random token with at least 32 characters and put the same value in .env.
export DREAMINA_BRIDGE_TOKEN="your-long-random-token"
uv run dramaclaw-dreamina-bridge --host 0.0.0.0 --port 8791
```

Configure the project `.env`:

```bash
DREAMINA_BRIDGE_URL=http://host.docker.internal:8791
DREAMINA_BRIDGE_TOKEN=the-same-long-random-token
DREAMINA_IMAGE_MODEL=5.0
```

Restart DramaClaw, then open Settings → Model Configuration → Dreamina Subscription and complete the official device-code login. The channel supports text-to-image, image-to-image, text-to-video, first-frame video, and first/last-frame video. Dreamina video output is currently limited to 720p and 4–15 seconds.

The bridge accepts only allowlisted Dreamina operations and parameters, uses Bearer authentication, and never copies OAuth tokens, cookies, or CLI login files into DramaClaw or the Git repository. Bind to `0.0.0.0` only so Docker Desktop can reach it through `host.docker.internal`; do not expose port 8791 to the public internet.

## A. DC official key (recommended, simplest)

The default `docker-compose.yml` already routes models through the "Official Channel". After `docker compose up -d --build` is running:

1. Open **`http://localhost:8080`** in your browser and go to Settings → **Model Configuration → Official Channel**.
2. The official gateway address is fixed as `https://relayclaw.cdnfg.com/v1`; **paste your DC key** and click "Save and Enable".
3. It works immediately — RelayClaw has all of DramaClaw's logical models configured on its backend, so **no `*_MODEL` mapping is required**.

> Don't have a DC key yet? Sign up / purchase at **<https://relayclaw.cdnfg.com>**.

## B. Local NewAPI

Fully local with no dependency on an external gateway: use the selfhosted orchestration, which additionally brings up a built-in `newapi` container:

```bash
docker compose -f docker-compose.selfhosted.yml up -d --build
```

On first start, open Settings → Model Configuration → Local NewAPI. The initialization flow creates the administrator and runtime token, then stores the runtime address and token in `settings.db`. Configure upstream channels and model mappings on the same page. See the [Self-Hosting Handbook](../guides/self-hosting.md) for details.

### Mapping logical model names

`.env.example` has roughly 30 `*_MODEL` entries that use logical names (e.g. `HERMES_MODEL=DC-hermes-LLM`, `SCENE_BUILD_MODEL=DC-scene-builder-LLM`). Two ways to handle them:

1. **Keep the logical names and map them to real upstream models in Local NewAPI** (recommended); or
2. **Change each `*_MODEL` to a model name your gateway actually provides.**

Grouped by purpose: text (Hermes/Cognee/the various planners/normalizers, etc.), image (`NEWAPI_IMAGE_MODEL`, `NEWAPI_NANOBANANA2_MODEL` and the various `*_IMAGE_*`), video (`VIDEO_BACKEND`, `NEWAPI_VIDEO_MODELS`…), audio (`INDEXTTS2_NEWAPI_MODEL`).

> When using a DC official key, skip this section — RelayClaw already has everything configured.

After changing the key or channel, new clients use the new settings. Hermes rotates its worker automatically. If Cognee has already initialized in the current process, restart DramaClaw before using the novel knowledge base again.

### Reference media (optional)

If you use "upload reference image", you need to configure an OSS relay (`OSS_RELAY_ENDPOINT/BUCKET/AK/SK`); plain-text workflows can leave it unconfigured for now.
