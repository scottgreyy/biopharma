"""
Thin HTTP client the Streamlit app uses to talk to the three backends.

Auth (register/login) is identical across all backends, so it can target any
one of them (we use the ReAct port by default). Chat is per-approach: each
approach has its own base URL/port, and its response shape differs slightly
(ReAct -> trace; Supervisor -> assignments/worker_outputs; Router -> plan/steps),
which the UI renders accordingly.
"""
from __future__ import annotations

from typing import Any

import requests

# Approach registry: label -> (base_url, response "trace" key for display).
APPROACHES: dict[str, dict[str, Any]] = {
    "ReAct Agent": {
        "base_url": "http://localhost:8001",
        "blurb": "Single agent, tool-calling loop (Thought → Action → Observation).",
    },
    "Multi-Agent Supervisor": {
        "base_url": "http://localhost:8002",
        "blurb": "LangGraph supervisor routes to Inventory/People workers.",
    },
    "Intent Router": {
        "base_url": "http://localhost:8003",
        "blurb": "LLM extracts JSON intent → parameterized DuckDB query library.",
    },
}

# The admin (data-management) backend — not a chat approach, so it's separate.
ADMIN_BASE_URL = "http://localhost:8004"

_TIMEOUT = 180  # generous: cloud LLM calls are network-bound and can be slow.


class APIError(Exception):
    pass


def _post(url: str, json: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.post(url, json=json, headers=headers, timeout=_TIMEOUT)
    except requests.exceptions.ConnectionError:
        raise APIError(
            f"Could not reach {url}. Is that backend running? "
            "Start it with the uvicorn command from the README."
        )
    except requests.exceptions.Timeout:
        raise APIError("The backend took too long to respond (LLM timeout).")
    if r.status_code >= 400:
        detail = ""
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = r.text
        raise APIError(f"{r.status_code}: {detail}")
    return r.json()


def register(username: str, password: str, base_url: str) -> str:
    data = _post(f"{base_url}/auth/register", {"username": username, "password": password})
    return data["access_token"]


def login(username: str, password: str, base_url: str) -> str:
    data = _post(f"{base_url}/auth/login", {"username": username, "password": password})
    return data["access_token"]


def chat(base_url: str, token: str, message: str, history: list[dict[str, str]]) -> dict[str, Any]:
    return _post(
        f"{base_url}/chat",
        {"message": message, "history": history},
        token=token,
    )


def health(base_url: str) -> dict[str, Any] | None:
    try:
        r = requests.get(f"{base_url}/health", timeout=5)
        return r.json() if r.status_code == 200 else None
    except requests.exceptions.RequestException:
        return None


# --------------------------------------------------------------------------
# Admin (data-management) client functions — target the admin backend (:8004)
# --------------------------------------------------------------------------
def _get(url: str, token: str) -> dict[str, Any]:
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    except requests.exceptions.ConnectionError:
        raise APIError(f"Could not reach the admin backend ({ADMIN_BASE_URL}). Is it running on port 8004?")
    if r.status_code >= 400:
        try:
            raise APIError(f"{r.status_code}: {r.json().get('detail','')}")
        except ValueError:
            raise APIError(f"{r.status_code}: {r.text}")
    return r.json()


def admin_list_assets(token: str, limit: int = 500) -> dict[str, Any]:
    return _get(f"{ADMIN_BASE_URL}/admin/assets?limit={limit}", token)


def admin_get_asset(token: str, code: str) -> dict[str, Any]:
    return _get(f"{ADMIN_BASE_URL}/admin/assets/{code}", token)


def admin_add_asset(token: str, asset: dict[str, str]) -> dict[str, Any]:
    return _post(f"{ADMIN_BASE_URL}/admin/assets", asset, token=token)


def admin_delete_asset(token: str, code: str) -> dict[str, Any]:
    try:
        r = requests.delete(
            f"{ADMIN_BASE_URL}/admin/assets/{code}",
            headers={"Authorization": f"Bearer {token}"}, timeout=30,
        )
    except requests.exceptions.ConnectionError:
        raise APIError(f"Could not reach the admin backend ({ADMIN_BASE_URL}).")
    if r.status_code >= 400:
        try:
            raise APIError(f"{r.status_code}: {r.json().get('detail','')}")
        except ValueError:
            raise APIError(f"{r.status_code}: {r.text}")
    return r.json()


def admin_upload(token: str, filename: str, content: bytes) -> dict[str, Any]:
    try:
        r = requests.post(
            f"{ADMIN_BASE_URL}/admin/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (filename, content)},
            timeout=60,
        )
    except requests.exceptions.ConnectionError:
        raise APIError(f"Could not reach the admin backend ({ADMIN_BASE_URL}).")
    if r.status_code >= 400:
        try:
            raise APIError(f"{r.json().get('detail','')}")
        except ValueError:
            raise APIError(f"{r.status_code}: {r.text}")
    return r.json()


def admin_health() -> bool:
    try:
        r = requests.get(f"{ADMIN_BASE_URL}/admin/assets", timeout=5)
        return r.status_code in (200, 401, 403)
    except requests.exceptions.RequestException:
        return False


# --------------------------------------------------------------------------
# Evaluation: run the labeled eval set against a backend's /chat endpoint.
# --------------------------------------------------------------------------
def chat_for_eval(base_url: str, token: str, message: str) -> dict[str, Any]:
    """A thin chat call used by the evaluation engine (no history)."""
    return _post(f"{base_url}/chat", {"message": message, "history": []}, token=token)

