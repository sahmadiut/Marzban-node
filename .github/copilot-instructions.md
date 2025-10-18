# AI assistant instructions for this repo

Purpose: This repo runs a secure control node for Xray core, exposing either an rpyc service or a REST API over TLS. The node receives an Xray JSON config, amends it to inject a local TLS-protected API inbound, then manages the Xray process lifecycle and streams logs.

Big picture
- Entry point: `main.py` chooses protocol via `SERVICE_PROTOCOL` (env) and starts either:
  - rpyc: `rpyc_service.XrayService` wrapped by `rpyc.utils.server.ThreadedServer` with TLS (`SSLAuthenticator`).
  - REST: FastAPI app from `rest_service.py` served by Uvicorn with mutual TLS (client cert required).
- Core control: `xray.py`
  - `XRayConfig` loads user config JSON and injects an API inbound (`dokodemo-door`, tag `API_INBOUND`) with TLS using `SSL_CERT_FILE`/`SSL_KEY_FILE`. It also filters inbounds by `INBOUNDS` env if set and ensures routing to `api.tag`.
  - `XRayCore` wraps the Xray binary (`XRAY_EXECUTABLE_PATH`, assets at `XRAY_ASSETS_PATH`), runs `xray run -config stdin:` and manages start/stop/restart, version detection, and log capture (deque + optional DEBUG printing). `get_logs()` yields a temporary deque of recent lines.
- Certificates: `certificate.generate_certificate()` creates a long-lived self-signed cert; `main.py` writes PEMs if files are missing.
- Config/env: `config.py` loads from env with `python-decouple`/dotenv; see defaults and keys there.
- Logging: `logger.py` sets colored console logs and plugs into Uvicorn’s formatter.

Security model
- Always TLS on the external interface; REST mode additionally requires a client certificate (`SSL_CLIENT_CERT_FILE`); startup aborts if it’s missing in REST mode.
- rpyc mode can optionally require client cert if `SSL_CLIENT_CERT_FILE` is provided to `SSLAuthenticator`.
- At REST level, a per-connection UUID `session_id` gates stateful operations and websocket logs.

Key files and roles
- `main.py`: bootstraps TLS files, validates client cert requirement, starts server.
- `rest_service.py`: endpoints: `/connect` -> session_id, `/start` `/stop` `/restart`, `/disconnect`, `/ping`, websocket `/logs` with optional `interval` batching.
- `rpyc_service.py`: exposes `start`, `stop`, `restart`, `fetch_xray_version`, `fetch_logs` (with a background thread aggregator).
- `xray.py`: modifies config, manages process, emits logs, on_start/on_stop hooks.
- `config.py`: env vars such as SERVICE_HOST/PORT, XRAY_API_HOST/PORT, XRAY_EXECUTABLE_PATH, XRAY_ASSETS_PATH, SSL_* paths, DEBUG, SERVICE_PROTOCOL, INBOUNDS.

Developer workflows
- Run locally (REST, default): ensure `xray` binary and assets exist at configured paths or override via env. Provide TLS certs in `SSL_CERT_FILE`/`SSL_KEY_FILE` (or let app autogenerate on first run) and a client CA in `SSL_CLIENT_CERT_FILE`.
  - Start: `python main.py` (FastAPI + Uvicorn). REST requires client cert; without it, app exits.
- Run with rpyc: set `SERVICE_PROTOCOL=rpyc`; client cert optional. Start `python main.py` and connect with an rpyc client using TLS.
- Docker: `docker-compose.yml` uses image `sahmadiut/marzban-node:latest` with `network_mode: host` and mounts `/var/lib/marzban-node` for cert persistence. Override envs as needed.
- Building image: `Dockerfile` builds deps and installs Xray via `install_latest_xray.sh`, then runs `python main.py`.

API usage examples (REST)
- Connect: POST `/connect` -> `{ session_id, connected, started, core_version }`.
- Start: POST `/start` with body `{ session_id: "<uuid>", config: "<xray-json-string>" }`. Config must be a JSON string; it’s wrapped by `XRayConfig` to inject API.
- Logs websocket: `wss://<host>:<port>/logs?session_id=<uuid>&interval=1.0` for batched lines, or omit interval for real-time.
- Error shapes: 422 embeds field-specific messages; 503 includes last startup log line on failures.

Project-specific conventions and pitfalls
- Config JSON is passed as a string field in POST bodies (not as nested JSON). Validate and return field-level 422 errors.
- `INBOUNDS` env lets you whitelist inbound tags; others are removed during `XRayConfig._apply_api()`.
- Log level: if user config sets `log.logLevel` to `none` or `error`, it’s overridden to at least `warning` for visibility.
- `XRayCore.get_version()` expects `xray version` to output like `Xray <semver>`; failures here indicate missing binary.
- REST mode mandates mutual TLS; rpyc uses SSLAuthenticator with optional CA; missing `SSL_CLIENT_CERT_FILE` is a hard error only in REST mode.

Extending or changing behavior
- New REST endpoints should be added via `Service.router.add_api_route` and include `session_id` checks via `match_session_id` when stateful.
- To stream logs to new consumers, reuse `XRayCore.get_logs()` contextmanager. For rpyc patterns, see `XrayCoreLogsHandler`.
- When touching Xray config shape, update both `XRayConfig._apply_api()` and tests/clients that expect `API_INBOUND` and routing rule at index 0.

Quick env reference
- SERVICE_PROTOCOL: `rest` (default) or `rpyc`
- SERVICE_HOST/SERVICE_PORT: external service bind
- XRAY_EXECUTABLE_PATH/XRAY_ASSETS_PATH: Xray binary/assets
- XRAY_API_HOST/XRAY_API_PORT: injected API inbound bind
- SSL_CERT_FILE/SSL_KEY_FILE: node server cert/key (auto-generated if absent)
- SSL_CLIENT_CERT_FILE: required CA/client cert path for REST; optional for rpyc
- DEBUG: boolean for verbose logs
- INBOUNDS: comma-separated list of inbound tags to keep

Testing/validation tips
- Start node and attempt `/connect` without a client cert to confirm mutual TLS enforcement (should fail at TLS).
- Provide a minimal Xray config with a single inbound; verify `API_INBOUND` is injected and startup logs include `Xray <version> started` within ~3s.
