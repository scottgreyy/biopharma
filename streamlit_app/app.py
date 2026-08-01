"""
Asset Management Assistant — Streamlit frontend.

Flow:
  1. Login / Register screen (JWT auth, shared across all backends).
  2. Landing: pick one of the three approaches.
  3. Per-approach chat: left sidebar switches approach + shows model/health +
     logout; main pane is the chat with an expandable reasoning trace per turn.

Short-term memory only: conversation history lives in st.session_state per
approach and is sent to the backend as `history`. Nothing is persisted.

Run:
    streamlit run streamlit_app/app.py
(Backends must be running on ports 8001/8002/8003.)
"""
from __future__ import annotations

import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from streamlit_app.api_client import (
    APPROACHES,
    APIError,
    chat as api_chat,
    health as api_health,
    login as api_login,
    register as api_register,
)

# Auth targets the ReAct backend by default (auth is identical on all three).
AUTH_BASE_URL = APPROACHES["ReAct Agent"]["base_url"]

st.set_page_config(page_title="Asset Management Assistant", page_icon="🗂️", layout="wide")


# --------------------------------------------------------------------------
# Session state initialization
# --------------------------------------------------------------------------
def _init_state() -> None:
    st.session_state.setdefault("token", None)
    st.session_state.setdefault("username", None)
    st.session_state.setdefault("approach", None)  # None => landing page
    # Per-approach chat history: {approach_label: [{"role","content"}, ...]}
    st.session_state.setdefault("histories", {label: [] for label in APPROACHES})


def _logout() -> None:
    for k in ("token", "username", "approach", "histories"):
        st.session_state.pop(k, None)
    _init_state()


# --------------------------------------------------------------------------
# Screen 1: Login / Register
# --------------------------------------------------------------------------
def render_auth() -> None:
    st.title("🗂️ Asset Management Assistant")
    st.caption("XYZ Technologies — sign in to continue")

    tab_login, tab_register = st.tabs(["Log in", "Create account"])

    with tab_login:
        u = st.text_input("Username", key="login_user")
        p = st.text_input("Password", type="password", key="login_pass")
        if st.button("Log in", type="primary", key="login_btn"):
            try:
                token = api_login(u, p, AUTH_BASE_URL)
                st.session_state.token = token
                st.session_state.username = u
                st.rerun()
            except APIError as e:
                st.error(str(e))

    with tab_register:
        u2 = st.text_input("Choose a username (min 3 chars)", key="reg_user")
        p2 = st.text_input("Choose a password (min 6 chars)", type="password", key="reg_pass")
        if st.button("Create account", type="primary", key="reg_btn"):
            try:
                token = api_register(u2, p2, AUTH_BASE_URL)
                st.session_state.token = token
                st.session_state.username = u2
                st.rerun()
            except APIError as e:
                st.error(str(e))

    st.info(
        "First time? Use **Create account**. Auth is shared across all three "
        "backends, so one login works everywhere.",
        icon="ℹ️",
    )


# --------------------------------------------------------------------------
# Screen 2: Landing — choose an approach
# --------------------------------------------------------------------------
def render_landing() -> None:
    st.title(f"Welcome, {st.session_state.username} 👋")
    st.subheader("Choose an approach")
    st.caption("Each approach is a separate backend implementing the assistant differently.")

    cols = st.columns(len(APPROACHES))
    for col, (label, meta) in zip(cols, APPROACHES.items()):
        with col:
            st.markdown(f"### {label}")
            st.write(meta["blurb"])
            h = api_health(meta["base_url"])
            if h:
                st.success(f"Online · {h.get('model', '?')}", icon="✅")
            else:
                st.warning(f"Offline ({meta['base_url']})", icon="⚠️")
            if st.button(f"Open {label}", key=f"open_{label}", use_container_width=True):
                st.session_state.approach = label
                st.rerun()

    st.divider()
    if st.button("Log out"):
        _logout()
        st.rerun()


# --------------------------------------------------------------------------
# Screen 3: Per-approach chat
# --------------------------------------------------------------------------
def _render_trace(approach: str, resp: dict) -> None:
    """Render the approach-specific reasoning trace in an expander."""
    with st.expander("🔍 Reasoning trace", expanded=False):
        if approach == "ReAct Agent":
            for step in resp.get("trace", []):
                st.markdown(f"**Step {step['step']} — `{step['tool']}`**")
                st.json({"arguments": step["arguments"], "observation": step["observation"]})
            if not resp.get("trace"):
                st.caption("No tools were called for this answer.")
        elif approach == "Multi-Agent Supervisor":
            st.markdown(f"**Supervisor routing** — _{resp.get('reason','')}_")
            st.json(resp.get("assignments", []))
            st.markdown("**Worker outputs**")
            st.json(resp.get("worker_outputs", []))
        elif approach == "Intent Router":
            st.markdown("**Extracted intent plan**")
            st.json(resp.get("plan", {}))
            st.markdown("**Execution steps**")
            st.json(resp.get("steps", []))


def render_chat() -> None:
    approach = st.session_state.approach
    meta = APPROACHES[approach]
    base_url = meta["base_url"]

    # ---- Left sidebar: approach switcher + status + logout ----
    with st.sidebar:
        st.header("Approaches")
        for label in APPROACHES:
            is_current = label == approach
            if st.button(
                ("▶ " if is_current else "　") + label,
                key=f"switch_{label}",
                use_container_width=True,
                type="primary" if is_current else "secondary",
            ):
                st.session_state.approach = label
                st.rerun()

        st.divider()
        h = api_health(base_url)
        if h:
            st.caption(f"**Model:** {h.get('model','?')}")
            st.caption(f"**Max concurrency:** {h.get('max_concurrency','?')}")
        else:
            st.warning("Backend offline", icon="⚠️")

        st.divider()
        if st.button("🏠 Back to landing", use_container_width=True):
            st.session_state.approach = None
            st.rerun()
        if st.button("🚪 Log out", use_container_width=True):
            _logout()
            st.rerun()
        if st.button("🧹 Clear this chat", use_container_width=True):
            st.session_state.histories[approach] = []
            st.rerun()

    # ---- Main pane: chat ----
    st.title(approach)
    st.caption(meta["blurb"])

    history = st.session_state.histories[approach]

    # Replay past turns.
    for turn in history:
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])
            if turn["role"] == "assistant" and "_resp" in turn:
                _render_trace(approach, turn["_resp"])

    # New input.
    prompt = st.chat_input(f"Ask the {approach} about company assets…")
    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)
        history.append({"role": "user", "content": prompt})

        # Send only clean role/content history (strip our _resp field).
        clean_history = [{"role": t["role"], "content": t["content"]} for t in history[:-1]]

        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    resp = api_chat(base_url, st.session_state.token, prompt, clean_history)
                    answer = resp.get("answer", "(no answer)")
                    st.markdown(answer)
                    _render_trace(approach, resp)
                    history.append({"role": "assistant", "content": answer, "_resp": resp})
                except APIError as e:
                    st.error(str(e))
                    # Roll back the user turn so retry is clean.
                    history.pop()


# --------------------------------------------------------------------------
# Router
# --------------------------------------------------------------------------
def main() -> None:
    _init_state()
    if not st.session_state.token:
        render_auth()
    elif st.session_state.approach is None:
        render_landing()
    else:
        render_chat()


if __name__ == "__main__":
    main()
