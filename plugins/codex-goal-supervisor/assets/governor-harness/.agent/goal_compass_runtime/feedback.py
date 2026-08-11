"""Low-overhead Goal Compass feedback capture and delivery.

Events are written to a durable local outbox. Network delivery is a separate,
project-scoped capability that stays disabled until the user explicitly grants
upload consent. Network failures never block product work. Payloads contain
governance metadata only; source text, prompts, environment values, and
credentials are not collected.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import platform
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .state_store import append_jsonl, exclusive_file_lock, load_json, utc_now_iso, write_json, write_json_exclusive


CONFIG_NAME = "feedback_config.json"
OUTBOX_DIR = "feedback-outbox"
DELIVERY_STATE = "feedback_delivery_state.json"
SENT_LOG = "feedback_sent.jsonl"
DELIVERY_LOCK = "feedback_delivery.lock"
CONFIG_SCHEMA_VERSION = 2
EVENT_SCHEMA_VERSION = 1
UPLOAD_CONSENT_VERSION = 1
MAX_TEXT = 2000
DEFAULT_TIMEOUT_SECONDS = 2.0
FAILURE_COOLDOWN_SECONDS = 300
VALID_DEPLOYMENT_CONTEXTS = {"unknown", "enterprise", "personal"}
GLOBAL_CONFIG_ENV = "GOAL_COMPASS_FEEDBACK_GLOBAL_CONFIG"
GLOBAL_TOKEN_FILE_ENV = "GOAL_COMPASS_FEEDBACK_TOKEN_FILE"
DISABLE_DEFAULT_ENDPOINT_ENV = "GOAL_COMPASS_FEEDBACK_DISABLE_DEFAULT_ENDPOINT"
DEFAULT_GLOBAL_CONFIG = Path.home() / ".codex" / "goal-supervisor-feedback.json"
DEFAULT_TOKEN_FILE = Path.home() / ".codex" / "secrets" / "goal-supervisor-feedback.token"
DEFAULT_ENDPOINT = "https://feedback.xn--15tf697cgrb.xyz/v1/events"
DEFAULT_REGISTRATION_ENDPOINT = "https://feedback.xn--15tf697cgrb.xyz/v1/devices/register"
DEVICE_CONFIG_SCHEMA_VERSION = 2
DEVICE_CLIENT_ID = "codex-goal-supervisor"
DEVICE_TOKEN_PREFIX = "gsvd_"

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|authorization)\b"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_TOKEN_SHAPES = re.compile(
    r"(?i)\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{20,}|Bearer\s+[A-Za-z0-9._~+/-]{12,})\b"
)


def default_config() -> dict[str, Any]:
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "capture_enabled": True,
        "deployment_context": "unknown",
        "upload_enabled": False,
        "upload_consent_at": None,
        "upload_consent_version": None,
        "endpoint": "",
        "token_env": "GOAL_COMPASS_FEEDBACK_TOKEN",
        "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
        "project_id": uuid.uuid4().hex,
        "privacy_mode": "governance_metadata_only",
        "delivery": "local_outbox_only",
    }


def upload_authorized(config: dict[str, Any]) -> bool:
    return (
        config.get("upload_enabled") is True
        and str(config.get("deployment_context") or "unknown") in {"enterprise", "personal"}
        and bool(config.get("upload_consent_at"))
        and config.get("upload_consent_version") == UPLOAD_CONSENT_VERSION
    )


def _normalize_config(current: dict[str, Any]) -> dict[str, Any]:
    merged = default_config()
    merged.update(current)
    merged["schema_version"] = CONFIG_SCHEMA_VERSION
    context = str(merged.get("deployment_context") or "unknown").strip().lower()
    merged["deployment_context"] = context if context in VALID_DEPLOYMENT_CONTEXTS else "unknown"

    # Schema v1 had no consent field. Preserve its endpoint, but never infer
    # permission to transmit from an old endpoint or environment variable.
    old_schema = int(current.get("schema_version", 0) or 0) < CONFIG_SCHEMA_VERSION
    if old_schema or "upload_enabled" not in current:
        merged["upload_enabled"] = False
        merged["upload_consent_at"] = None
        merged["upload_consent_version"] = None
    elif not upload_authorized(merged):
        merged["upload_enabled"] = False
        merged["upload_consent_at"] = None
        merged["upload_consent_version"] = None
    merged["delivery"] = "realtime_with_durable_outbox" if upload_authorized(merged) else "local_outbox_only"
    return merged


def ensure_config(agent_dir: Path = Path(".agent")) -> dict[str, Any]:
    path = agent_dir / CONFIG_NAME
    current = load_json(path, {})
    if not isinstance(current, dict) or not current:
        current = default_config()
        write_json(path, current)
        return current
    merged = _normalize_config(current)
    if merged != current:
        write_json(path, merged)
    return merged


def configure(
    *,
    agent_dir: Path = Path(".agent"),
    endpoint: str | None = None,
    token_env: str | None = None,
    capture_enabled: bool | None = None,
    timeout_seconds: float | None = None,
    deployment_context: str | None = None,
    upload_enabled: bool | None = None,
    confirm_upload: bool = False,
) -> dict[str, Any]:
    config = ensure_config(agent_dir)
    if endpoint is not None:
        config["endpoint"] = endpoint.strip()
    if token_env is not None:
        config["token_env"] = token_env.strip() or "GOAL_COMPASS_FEEDBACK_TOKEN"
    if capture_enabled is not None:
        config["capture_enabled"] = bool(capture_enabled)
    if timeout_seconds is not None:
        config["timeout_seconds"] = max(0.2, min(float(timeout_seconds), 5.0))
    if deployment_context is not None:
        normalized_context = deployment_context.strip().lower()
        if normalized_context not in VALID_DEPLOYMENT_CONTEXTS:
            raise ValueError("deployment context must be unknown, enterprise, or personal")
        if normalized_context != config.get("deployment_context") and upload_enabled is not True:
            config["upload_enabled"] = False
            config["upload_consent_at"] = None
            config["upload_consent_version"] = None
        config["deployment_context"] = normalized_context
    if upload_enabled is True:
        if not confirm_upload:
            raise ValueError("explicit --confirm-upload is required before feedback can leave this project")
        if config.get("deployment_context") not in {"enterprise", "personal"}:
            raise ValueError("set --context enterprise or --context personal before allowing upload")
        config["upload_enabled"] = True
        config["upload_consent_at"] = utc_now_iso()
        config["upload_consent_version"] = UPLOAD_CONSENT_VERSION
    elif upload_enabled is False:
        config["upload_enabled"] = False
        config["upload_consent_at"] = None
        config["upload_consent_version"] = None
    config = _normalize_config(config)
    write_json(agent_dir / CONFIG_NAME, config)
    return config


def _redact(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "<truncated>"
    if isinstance(value, str):
        text = value[:MAX_TEXT]
        home = str(Path.home())
        if home:
            text = text.replace(home, "<HOME>")
        text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
        return _TOKEN_SHAPES.sub("[REDACTED]", text)
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 30:
                cleaned["_truncated"] = True
                break
            low = str(key).lower()
            if any(term in low for term in ("prompt", "source_text", "file_content", "environment", "secret", "password", "token")):
                continue
            cleaned[str(key)[:120]] = _redact(item, depth + 1)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_redact(item, depth + 1) for item in list(value)[:30]]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _redact(str(value), depth + 1)


def _project_fingerprint(config: dict[str, Any]) -> str:
    seed = f"{config.get('project_id', '')}:{Path.cwd().resolve()}"
    return hashlib.sha256(seed.encode("utf-8", errors="replace")).hexdigest()[:24]


def _plugin_version(agent_dir: Path) -> str | None:
    provenance = load_json(agent_dir / "goal_compass_install.json", {})
    return str(provenance.get("plugin_version")) if isinstance(provenance, dict) and provenance.get("plugin_version") else None


def _runtime_paths(agent_dir: Path) -> tuple[Path, Path, Path]:
    runtime = agent_dir / "runtime"
    return runtime / OUTBOX_DIR, runtime / DELIVERY_STATE, runtime / SENT_LOG


def _global_config_path() -> Path:
    raw = os.environ.get(GLOBAL_CONFIG_ENV, "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_GLOBAL_CONFIG


def _default_token_path() -> Path:
    explicit = os.environ.get(GLOBAL_TOKEN_FILE_ENV, "").strip()
    if explicit:
        return Path(explicit).expanduser()
    if os.environ.get(GLOBAL_CONFIG_ENV, "").strip():
        return _global_config_path().with_name("goal-supervisor-feedback.token")
    return DEFAULT_TOKEN_FILE


def _default_device_config() -> dict[str, Any]:
    return {
        "schema_version": DEVICE_CONFIG_SCHEMA_VERSION,
        "endpoint": DEFAULT_ENDPOINT,
        "registration_endpoint": DEFAULT_REGISTRATION_ENDPOINT,
        "token_file": str(_default_token_path()),
        "credential_mode": "auto_registered_device",
    }


def _global_delivery_config() -> dict[str, Any]:
    raw = os.environ.get(GLOBAL_CONFIG_ENV, "").strip()
    path = _global_config_path()
    try:
        value = load_json(path, {})
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    # Tests and managed deployments can set an explicit config path to disable
    # the public default. Normal installations get a zero-configuration
    # endpoint, but it is never contacted before project-level consent.
    if raw and not value and os.environ.get(DISABLE_DEFAULT_ENDPOINT_ENV) == "1":
        return {}
    merged = _default_device_config()
    merged.update(value)
    if value.get("endpoint") and not value.get("registration_endpoint"):
        custom_endpoint = str(value["endpoint"])
        merged["registration_endpoint"] = (
            custom_endpoint[: -len("/v1/events")] + "/v1/devices/register"
            if custom_endpoint.endswith("/v1/events") else ""
        )
    return merged


def _lock_path(agent_dir: Path) -> Path:
    return agent_dir / "runtime" / DELIVERY_LOCK


def _delivery_state(agent_dir: Path) -> dict[str, Any]:
    _, state_path, _ = _runtime_paths(agent_dir)
    state = load_json(state_path, {})
    return state if isinstance(state, dict) else {}


def _write_delivery_state(agent_dir: Path, state: dict[str, Any]) -> None:
    _, state_path, _ = _runtime_paths(agent_dir)
    write_json(state_path, state)


def _endpoint(config: dict[str, Any]) -> str:
    shared = _global_delivery_config()
    return str(
        os.environ.get("GOAL_COMPASS_FEEDBACK_URL")
        or config.get("endpoint")
        or shared.get("endpoint")
        or ""
    ).strip()


def _registration_endpoint(config: dict[str, Any]) -> str:
    shared = _global_delivery_config()
    explicit = str(
        os.environ.get("GOAL_COMPASS_FEEDBACK_REGISTRATION_URL")
        or shared.get("registration_endpoint")
        or ""
    ).strip()
    if explicit:
        return explicit
    endpoint = _endpoint(config)
    if endpoint.endswith("/v1/events"):
        return endpoint[: -len("/v1/events")] + "/v1/devices/register"
    return ""


def _token_from_file(path_value: str) -> str:
    if not path_value:
        return ""
    path = Path(path_value).expanduser()
    try:
        if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
            return ""
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _auth_header(config: dict[str, Any]) -> str | None:
    shared = _global_delivery_config()
    env_name = str(config.get("token_env") or "GOAL_COMPASS_FEEDBACK_TOKEN")
    token = os.environ.get(env_name, "").strip()
    if not token:
        token_file = str(os.environ.get(GLOBAL_TOKEN_FILE_ENV) or shared.get("token_file") or "").strip()
        token = _token_from_file(token_file)
    return f"Bearer {token}" if token else None


def _credentials_configured(config: dict[str, Any]) -> bool:
    """Return whether this device has usable delivery credentials."""
    return _auth_header(config) is not None


def _atomic_private_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        if os.name != "nt":
            temp.chmod(0o600)
        os.replace(temp, path)
        if os.name != "nt":
            path.chmod(0o600)
    finally:
        temp.unlink(missing_ok=True)


def _open_request(request: urllib.request.Request, endpoint: str, timeout: float):
    hostname = urllib.parse.urlparse(endpoint).hostname or ""
    bypass_proxy = hostname.lower() in {"localhost", "localhost.localdomain"}
    try:
        bypass_proxy = bypass_proxy or ipaddress.ip_address(hostname).is_private
    except ValueError:
        pass
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if bypass_proxy else urllib.request.build_opener()
    return opener.open(request, timeout=timeout)


def _provision_device_credentials(config: dict[str, Any], agent_dir: Path) -> tuple[bool, str]:
    if _credentials_configured(config):
        return True, "credentials_present"
    registration_endpoint = _registration_endpoint(config)
    endpoint = _endpoint(config)
    if not registration_endpoint or not endpoint:
        return False, "automatic_registration_endpoint_unavailable"

    shared = _global_delivery_config()
    config_path = _global_config_path()
    token_path = Path(
        str(os.environ.get(GLOBAL_TOKEN_FILE_ENV) or shared.get("token_file") or _default_token_path())
    ).expanduser()
    install_id = str(shared.get("install_id") or uuid.uuid4().hex)
    payload = {
        "schema_version": 1,
        "client": DEVICE_CLIENT_ID,
        "install_id": install_id,
        "plugin_version": _plugin_version(agent_dir) or "unknown",
        "platform": platform.system() or "unknown",
    }
    request = urllib.request.Request(
        registration_endpoint,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "codex-goal-supervisor-device-registration/1",
        },
        method="POST",
    )
    timeout = max(0.2, min(float(config.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS), 5.0))
    try:
        with _open_request(request, registration_endpoint, timeout) as response:
            code = int(getattr(response, "status", 200) or 200)
            response_body = response.read(16 * 1024)
        if not 200 <= code < 300:
            return False, f"registration_http_{code}"
        result = json.loads(response_body.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return False, f"registration_http_{exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return False, f"registration_{type(exc).__name__}"
    if not isinstance(result, dict):
        return False, "registration_invalid_response"
    token = str(result.get("token") or "")
    device_id = str(result.get("device_id") or "")
    if not token.startswith(DEVICE_TOKEN_PREFIX) or len(token) < len(DEVICE_TOKEN_PREFIX) + 32 or not device_id:
        return False, "registration_invalid_credentials"

    device_config = _default_device_config()
    device_config.update({
        key: value for key, value in shared.items()
        if key not in {"token", "authorization", "password", "secret"}
    })
    device_config.update({
        "schema_version": DEVICE_CONFIG_SCHEMA_VERSION,
        "endpoint": endpoint,
        "registration_endpoint": registration_endpoint,
        "token_file": str(token_path),
        "credential_mode": "auto_registered_device",
        "device_id": device_id,
        "install_id": install_id,
        "registered_at": utc_now_iso(),
    })
    try:
        _atomic_private_write(token_path, token + "\n")
        _atomic_private_write(config_path, json.dumps(device_config, ensure_ascii=False, indent=2) + "\n")
    except OSError as exc:
        return False, f"registration_storage_{type(exc).__name__}"
    return True, "device_registered"


def _clear_auto_registered_token() -> None:
    shared = _global_delivery_config()
    if shared.get("credential_mode") != "auto_registered_device":
        return
    token_path = Path(str(shared.get("token_file") or _default_token_path())).expanduser()
    try:
        token_path.unlink(missing_ok=True)
    except OSError:
        return


def _post(event: dict[str, Any], config: dict[str, Any]) -> tuple[bool, str]:
    endpoint = _endpoint(config)
    if not endpoint:
        return False, "endpoint_not_configured"
    body = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "codex-goal-supervisor-feedback/1",
    }
    auth = _auth_header(config)
    if not auth:
        return False, "credentials_missing"
    headers["Authorization"] = auth
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    timeout = max(0.2, min(float(config.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS), 5.0))
    try:
        with _open_request(request, endpoint, timeout) as response:
            code = int(getattr(response, "status", 200) or 200)
        return (200 <= code < 300), f"http_{code}"
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, type(exc).__name__


def _cooldown_active(state: dict[str, Any]) -> bool:
    retry_after = str(state.get("retry_after") or "")
    if not retry_after:
        return False
    try:
        from datetime import datetime, timezone

        return datetime.fromisoformat(retry_after.replace("Z", "+00:00")) > datetime.now(timezone.utc)
    except ValueError:
        return False


def _set_failure_cooldown(state: dict[str, Any], reason: str) -> None:
    from datetime import datetime, timedelta, timezone

    state["last_error"] = reason
    state["last_failed_at"] = utc_now_iso()
    state["retry_after"] = (datetime.now(timezone.utc) + timedelta(seconds=FAILURE_COOLDOWN_SECONDS)).replace(microsecond=0).isoformat()


def _flush_unlocked(*, agent_dir: Path, max_events: int, force: bool) -> dict[str, Any]:
    config = ensure_config(agent_dir)
    outbox, _, sent_log = _runtime_paths(agent_dir)
    state = _delivery_state(agent_dir)
    try:
        pending = sum(1 for _ in outbox.glob("*.json"))
    except OSError:
        pending = int(state.get("pending", 0) or 0)
    if not upload_authorized(config):
        state["pending"] = pending
        _write_delivery_state(agent_dir, state)
        return {"sent": 0, "pending": pending, "status": "LOCAL_ONLY"}
    if not _endpoint(config):
        return {"sent": 0, "pending": pending, "status": "AUTHORIZED_UNCONFIGURED"}
    if _cooldown_active(state) and not force:
        return {"sent": 0, "pending": pending, "status": "COOLDOWN", "last_error": state.get("last_error")}
    if not _credentials_configured(config):
        provisioned, provision_result = _provision_device_credentials(config, agent_dir)
        if not provisioned:
            state["pending"] = pending
            _set_failure_cooldown(state, provision_result)
            _write_delivery_state(agent_dir, state)
            return {
                "sent": 0,
                "pending": pending,
                "status": "AUTHORIZED_DEVICE_REGISTRATION_FAILED",
                "last_error": provision_result,
            }
    sent = 0
    outbox.mkdir(parents=True, exist_ok=True)
    for path in sorted(outbox.glob("*.json"))[: max(1, min(int(max_events), 100))]:
        event = load_json(path, {})
        if not isinstance(event, dict) or not event:
            path.unlink(missing_ok=True)
            continue
        ok, result = _post(event, config)
        if not ok and result == "http_401":
            _clear_auto_registered_token()
            provisioned, provision_result = _provision_device_credentials(config, agent_dir)
            if provisioned:
                ok, result = _post(event, config)
            else:
                result = provision_result
        if not ok:
            _set_failure_cooldown(state, result)
            break
        path.unlink(missing_ok=True)
        sent += 1
        append_jsonl(sent_log, {
            "event_id": event.get("event_id"),
            "event_fingerprint": event.get("event_fingerprint"),
            "sent_at": utc_now_iso(),
            "result": result,
        })
        state["last_sent_at"] = utc_now_iso()
        state["last_error"] = None
        state["retry_after"] = None
    try:
        pending = sum(1 for _ in outbox.glob("*.json"))
    except OSError:
        pending = int(state.get("pending", 0) or 0)
    state["pending"] = pending
    state["sent_total"] = int(state.get("sent_total", 0) or 0) + sent
    _write_delivery_state(agent_dir, state)
    return {
        "sent": sent,
        "pending": pending,
        "status": "DELIVERED" if sent else "PENDING",
        "last_error": state.get("last_error"),
    }


def flush(*, agent_dir: Path = Path(".agent"), max_events: int = 10, force: bool = False) -> dict[str, Any]:
    try:
        with exclusive_file_lock(_lock_path(agent_dir), timeout=0.5, stale_seconds=30.0):
            return _flush_unlocked(agent_dir=agent_dir, max_events=max_events, force=force)
    except RuntimeError:
        state = _delivery_state(agent_dir)
        return {
            "sent": 0,
            "pending": int(state.get("pending", 0) or 0),
            "status": "BUSY",
            "last_error": state.get("last_error"),
        }


def record(
    *,
    kind: str,
    message: str,
    source: str,
    severity: str = "warning",
    rule_id: str | None = None,
    command: str | None = None,
    ticket_id: str | None = None,
    status: str | None = None,
    context: dict[str, Any] | None = None,
    agent_dir: Path = Path(".agent"),
    request_iteration: bool = True,
) -> dict[str, Any]:
    config = ensure_config(agent_dir)
    if config.get("capture_enabled") is False:
        return {"captured": False, "delivery": "DISABLED"}
    event_id = uuid.uuid4().hex
    clean_message = str(_redact(message))
    fingerprint_seed = "|".join([kind, str(rule_id or ""), str(status or ""), clean_message])
    event = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": event_id,
        "event_fingerprint": hashlib.sha256(fingerprint_seed.encode("utf-8")).hexdigest(),
        "occurred_at": utc_now_iso(),
        "project_fingerprint": _project_fingerprint(config),
        "plugin_version": _plugin_version(agent_dir),
        "runtime": {"os": platform.system(), "python": f"{sys.version_info.major}.{sys.version_info.minor}"},
        "source": source,
        "kind": kind,
        "severity": severity,
        "rule_id": rule_id,
        "command": command,
        "ticket_id": ticket_id,
        "status": status,
        "message": clean_message,
        "context": _redact(context or {}),
        "privacy_mode": "governance_metadata_only",
        "maintainer_action": "OPEN_REPRODUCTION_AND_REPAIR_TICKET" if request_iteration else "OBSERVE",
    }
    outbox, _, _ = _runtime_paths(agent_dir)
    outbox.mkdir(parents=True, exist_ok=True)
    write_json_exclusive(outbox / f"{event_id}.json", event)
    try:
        with exclusive_file_lock(_lock_path(agent_dir), timeout=0.5, stale_seconds=30.0):
            state = _delivery_state(agent_dir)
            state["pending"] = int(state.get("pending", 0) or 0) + 1
            state["last_captured_at"] = event["occurred_at"]
            state["last_event_fingerprint"] = event["event_fingerprint"]
            _write_delivery_state(agent_dir, state)
    except RuntimeError:
        pass
    delivery = flush(agent_dir=agent_dir, max_events=10)
    queued_locally = (outbox / f"{event_id}.json").exists()
    return {
        "captured": True,
        "event_id": event_id,
        "uploaded": upload_authorized(config) and not queued_locally,
        "queued_locally": queued_locally,
        "delivery": delivery,
    }


def status(agent_dir: Path = Path(".agent")) -> dict[str, Any]:
    config = ensure_config(agent_dir)
    state = _delivery_state(agent_dir)
    authorized = upload_authorized(config)
    remote_configured = bool(_endpoint(config))
    credentials_configured = _credentials_configured(config)
    upload_ready = authorized and remote_configured and credentials_configured
    if not authorized:
        delivery_status = "LOCAL_ONLY"
    elif not remote_configured:
        delivery_status = "AUTHORIZED_UNCONFIGURED"
    elif not credentials_configured:
        delivery_status = (
            "AUTHORIZED_DEVICE_REGISTRATION_FAILED"
            if str(state.get("last_error") or "").startswith("registration_") and _cooldown_active(state)
            else "AUTHORIZED_DEVICE_REGISTRATION_PENDING"
        )
    else:
        delivery_status = "COOLDOWN" if _cooldown_active(state) else "READY"
    return {
        "capture_enabled": config.get("capture_enabled") is not False,
        "deployment_context": config.get("deployment_context"),
        "privacy_choice_required": config.get("deployment_context") == "unknown",
        "upload_authorized": authorized,
        "remote_configured": remote_configured,
        "credentials_configured": credentials_configured,
        "upload_ready": upload_ready,
        "delivery_mode": config.get("delivery"),
        "pending": int(state.get("pending", 0) or 0),
        "sent_total": int(state.get("sent_total", 0) or 0),
        "last_captured_at": state.get("last_captured_at"),
        "last_sent_at": state.get("last_sent_at"),
        "delivery_status": delivery_status,
        "privacy_mode": config.get("privacy_mode"),
    }
