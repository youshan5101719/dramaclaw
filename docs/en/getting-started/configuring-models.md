<!-- lang-switch -->
**English** · [简体中文](../../zh/getting-started/configuring-models.md)

# Configuring Model Providers

DramaClaw CE connects text, image, video, audio, and embedding models through an OpenAI-compatible NewAPI gateway. You can use the official RelayClaw channel, the bundled local NewAPI, or a Dreamina subscription for media generation.

## Choose an access method

| Method | Best for | Model mapping required? |
|---|---|---|
| Official channel / RelayClaw | Fastest setup with official preconfigured models | No |
| Local NewAPI | Managing upstream channels, model mappings, media models, and embeddings in the DramaClaw UI | Yes, save mappings in the UI |
| Dreamina subscription | Using an existing premium subscription and its credits through the official Dreamina CLI | Bypasses NewAPI; requires a host bridge |

## Configuration entry point

Open `http://localhost:8080` and go to Settings -> Model Configuration. The selected channel, gateway address, and token are stored in local `settings.db`, not in environment variables.

The page supports:

- Official channel: paste a RelayClaw DC key and click Save and Enable.
- Local NewAPI: initialize NewAPI, create or reuse a runtime token, configure upstream channels, and save model mappings.
- Media storage: configure Aliyun OSS or Cloudinary.
- Embedding: configure the model, dimensions, and batch size.

New tasks use saved changes to keys, channels, or models. Tasks already running do not switch configuration mid-run.

## Dreamina subscription account (official CLI)

The Dreamina subscription is an independent media backend. It does not disguise OAuth state as a NewAPI API key. It uses the official Dreamina CLI Device Flow and supports text-to-image, image-to-image, text-to-video, image-to-video, and first/last-frame video. Text models, embeddings, and other provider channels continue to use NewAPI.

The official `dreamina` CLI runs on macOS while the DramaClaw API normally runs in a Linux Docker container, so start the constrained bridge on the host:

```bash
# Generate a random token of at least 32 characters and put the same value in .env.
export DREAMINA_BRIDGE_TOKEN="your-long-random-token"
uv run dramaclaw-dreamina-bridge --host 0.0.0.0 --port 8791
```

Configure the project `.env`:

```bash
DREAMINA_BRIDGE_URL=http://host.docker.internal:8791
DREAMINA_BRIDGE_TOKEN=the-same-random-token
DREAMINA_IMAGE_MODEL=5.0
```

Restart DramaClaw, then open Settings -> Model Configuration -> Dreamina Subscription. Click Sign in to Dreamina, enter the device code on the official authorization page, and click Check Login. After login, the UI shows membership and remaining credits. Project model selectors expose Dreamina subscription options for Seedream 5.0 images and Seedance 2.0 Fast videos.

Security boundary: the bridge authenticates with a random bearer token, accepts only allowlisted parameter values, and invokes approved Dreamina subcommands with `create_subprocess_exec`. It accepts no shell commands and never copies OAuth tokens, cookies, or CLI login files into DramaClaw or the Git repository. `--host 0.0.0.0` allows Docker Desktop to reach it through `host.docker.internal`; never expose port 8791 to the public internet.

## A. Official channel / RelayClaw (recommended)

The default `docker-compose.yml` uses the official channel:

1. Open `http://localhost:8080`.
2. Go to Settings -> Model Configuration -> Official Channel.
3. The gateway is fixed to `https://relayclaw.cdnfg.com/v1`.
4. Paste your DC key and click Save and Enable.

RelayClaw already maps every logical model required by DramaClaw, so no `*_MODEL` mapping is needed. Get a key at <https://relayclaw.cdnfg.com>.

## B. Local NewAPI

Local NewAPI lets a single-machine CE installation manage:

- The NewAPI runtime token.
- Upstream provider channels and keys.
- Text, multimodal, image, video, and audio model mappings.
- Cognee embedding model, dimensions, and batch size.

### 1. Start bundled NewAPI

For a source deployment:

```bash
docker compose -f docker-compose.selfhosted.yml up -d --build
```

For published images:

```bash
docker compose -f docker-compose.selfhosted.release.yml up -d
```

Both variants start `api`, `web`, and `newapi`. The NewAPI console is available at `http://localhost:3000`. The `newapi-data` volume is mounted at `/data` in NewAPI and `/newapi-data` in the DramaClaw API, allowing the initialization wizard to create the administrator and runtime token without manual token copying.

### 2. Initialize

Open Settings -> Model Configuration -> Local NewAPI:

1. If NewAPI is not initialized, enter the initial root administrator password.
2. Click Initialize Local NewAPI.

The wizard creates the administrator when needed, creates or reuses the `dramaclaw-ce-runtime` token, saves it to DramaClaw's local settings, and switches the gateway mode to `custom`. The password is used only for first-time setup and is not stored by DramaClaw. If NewAPI was initialized previously, leave the password empty; initialization reuses or creates the runtime token without resetting the administrator password.

### 3. Configure provider channels

Provider channels store upstream keys and optional base URL overrides, such as Ali, OpenRouter, OpenAI, or Midjourney.

- Save Channel Configuration stores a local preset but does not immediately change NewAPI.
- Update NewAPI Channel immediately updates that channel in NewAPI.
- Save Model Mappings writes the required channels and model aliases to NewAPI and saves the local configuration.

When a logical model changes provider, saving mappings removes it from the old channel before adding it to the new channel, preventing random routing between duplicate aliases.

### 4. Map logical models

Keep DramaClaw's internal logical model names unchanged and map them to real upstream models in NewAPI. The UI groups them as:

- Text-only models: Hermes, Cognee, identity/scene/prop planners, content rewriting, script normalization, and similar tasks.
- Multimodal models: prompt optimization, image-based identity/prop color detection, and style extraction. These require visual-input support.
- Embedding: `DC-cognee-embedding` for novel import, graph construction, and vector retrieval.
- Image: `LingShan-G2`, `LingShan-NB-2`, and scene/character/sketch image aliases.
- Video: `seedance-*`, `happyhorse-1.0`, and related aliases.
- Audio: `index-tts-2`, `LingShan-MU-11`, and related aliases.

Bulk-fill controls update the current page draft only. Review individual rows, then click Save Mappings to write the configuration.

## Embedding batch size

Cognee batches embedding requests. The default is 36:

```bash
EMBEDDING_BATCH_SIZE=36
```

Gemini-style embedding models commonly accept 36 inputs, while some Qwen/Ali models have lower limits and may need a value such as 10. For HTTP 400/422 during novel import or graph construction, check the model's supported dimensions, lower the batch size, and confirm that `DC-cognee-embedding` maps to the correct embedding model.

## Reference media relay

When an upstream model needs a local reference image, first frame, character image, or identity asset, DramaClaw uploads it to a temporary publicly reachable signed URL. Text-only and pure text-to-image workflows usually do not require a relay; reference-image and reference-video workflows do.

### Aliyun OSS

```bash
MEDIA_RELAY_PROVIDER=aliyun_oss
OSS_RELAY_ENDPOINT=oss-cn-chengdu.aliyuncs.com
OSS_RELAY_BUCKET=your_bucket
OSS_RELAY_AK=your_access_key_id
OSS_RELAY_SK=your_access_key_secret
MEDIA_RELAY_TTL_SECONDS=1800
```

Use a bucket-scoped RAM account rather than a primary account key. The bucket can remain private because DramaClaw generates temporary signed URLs.

### Cloudinary

```bash
MEDIA_RELAY_PROVIDER=cloudinary
CLOUDINARY_RELAY_CLOUD_NAME=your_cloud_name
CLOUDINARY_RELAY_API_KEY=your_api_key
CLOUDINARY_RELAY_API_SECRET=your_api_secret
CLOUDINARY_RELAY_FOLDER=relay
MEDIA_RELAY_TTL_SECONDS=1800
```

`CLOUDINARY_RELAY_FOLDER` is a Cloudinary folder name, not a local filesystem path. Saved credentials are stored locally and the backend does not return full secrets to the frontend.

## Troubleshooting

| Symptom | Resolution |
|---|---|
| Official channel still uses an old key | Confirm the official channel is active. New tasks use the new key; restart DramaClaw if Cognee was already initialized. |
| Local NewAPI initialization fails | Confirm NewAPI is running, its SQLite directories are writable, and `NEWAPI_PROVISIONER_ENABLED=true`. |
| NewAPI reports `No available channel for model ...` | Save a mapping for the logical model and confirm its channel is enabled. |
| Requests occasionally use the previous provider | Remove duplicate logical aliases from old NewAPI channels or save mappings again. |
| Embedding graph build returns 400/422 | Lower `EMBEDDING_BATCH_SIZE` and verify the embedding model, dimensions, and channel mapping. |
| Reference image or first-frame upload fails | Check OSS or Cloudinary settings; reference-media workflows require a configured relay. |

## Related files

- `.env.example`: complete environment variable list and defaults.
- `docker-compose.yml`: default official-channel deployment.
- `docker-compose.selfhosted.yml`: source-built deployment with bundled NewAPI.
- `docker-compose.selfhosted.release.yml`: published-image deployment with bundled NewAPI.
- [Self-Hosting Handbook](../guides/self-hosting.md)
- [Environment Variables Reference](../reference/environment-variables.md)
