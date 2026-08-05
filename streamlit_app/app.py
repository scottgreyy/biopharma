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
    admin_list_assets,
    admin_get_asset,
    admin_add_asset,
    admin_delete_asset,
    admin_upload,
    admin_health,
    chat_for_eval,
)

import asyncio
from shared.eval.engine import run_eval
from shared.llm.ollama_client import chat as _llm_chat

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
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("🗄️ Manage Data", use_container_width=True):
            st.session_state.approach = "__admin__"
            st.rerun()
    with col_b:
        if st.button("📊 Evaluation", use_container_width=True):
            st.session_state.approach = "__eval__"
            st.rerun()
    with col_c:
        if st.button("Log out", use_container_width=True):
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
        if st.button("🗄️ Manage Data", use_container_width=True):
            st.session_state.approach = "__admin__"
            st.rerun()
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
# Screen 4: Manage Data (admin backend :8004)
# --------------------------------------------------------------------------
def render_admin() -> None:
    token = st.session_state.token

    with st.sidebar:
        st.header("Navigation")
        for label in APPROACHES:
            if st.button(label, key=f"admin_to_{label}", use_container_width=True):
                st.session_state.approach = label
                st.rerun()
        st.divider()
        if st.button("🏠 Back to landing", use_container_width=True):
            st.session_state.approach = None
            st.rerun()
        if st.button("🚪 Log out", use_container_width=True):
            _logout()
            st.rerun()

    st.title("🗄️ Manage Data")
    if not admin_health():
        st.error("Admin backend is offline. Start it on port 8004 (it's part of run.bat).")
        return
    st.caption("View, look up, add, delete, and upload assets. Changes apply to all approaches.")

    tab_view, tab_lookup, tab_add, tab_delete, tab_upload = st.tabs(
        ["📋 View table", "🔎 Look up", "➕ Add", "🗑️ Delete", "⬆️ Upload"]
    )

    with tab_view:
        try:
            data = admin_list_assets(token)
            st.caption(f"Total assets: **{data['total']}**")
            st.dataframe(data["assets"], use_container_width=True, hide_index=True)
        except APIError as e:
            st.error(str(e))

    with tab_lookup:
        code = st.text_input("Asset code", key="lookup_code", placeholder="e.g. AST1002")
        if st.button("Look up", key="lookup_btn"):
            try:
                row = admin_get_asset(token, code.strip())
                st.success("Found:")
                st.json(row)
            except APIError as e:
                st.warning(str(e))

    with tab_add:
        st.caption("All fields required.")
        c1, c2 = st.columns(2)
        with c1:
            a_code = st.text_input("Asset Code", key="add_code")
            a_name = st.text_input("Asset Name", key="add_name")
            a_cat = st.text_input("Category", key="add_cat")
        with c2:
            a_emp = st.text_input("Employee Name", key="add_emp")
            a_loc = st.text_input("Location", key="add_loc")
            a_date = st.text_input("Purchase Date", key="add_date", placeholder="e.g. 18-Jan-24")
        if st.button("Add asset", key="add_btn", type="primary"):
            fields = {
                "asset_code": a_code, "asset_name": a_name, "category": a_cat,
                "employee_name": a_emp, "location": a_loc, "purchase_date": a_date,
            }
            if not all(v.strip() for v in fields.values()):
                st.error("Please fill in all six fields.")
            else:
                try:
                    r = admin_add_asset(token, fields)
                    st.success(r.get("message", "Added."))
                except APIError as e:
                    st.error(str(e))

    with tab_delete:
        d_code = st.text_input("Asset code to delete", key="del_code", placeholder="e.g. AST1002")
        confirm = st.checkbox("I understand this permanently deletes the row.", key="del_confirm")
        if st.button("Delete asset", key="del_btn", type="primary", disabled=not confirm):
            try:
                r = admin_delete_asset(token, d_code.strip())
                st.success(r.get("message", "Deleted."))
            except APIError as e:
                st.warning(str(e))

    with tab_upload:
        st.caption(
            "Upload CSV, Excel (.xlsx/.xls), or JSON. Columns must exactly match: "
            "Asset Code, Asset Name, Category, Employee Name, Location, Purchase Date. "
            "If they differ, the file is refused. Existing asset codes are rejected "
            "(no overwrite)."
        )
        up = st.file_uploader("Choose a file", type=["csv", "xlsx", "xls", "json"], key="uploader")
        if up is not None and st.button("Upload & append", key="upload_btn", type="primary"):
            try:
                r = admin_upload(token, up.name, up.getvalue())
                st.success(r.get("message", "Uploaded."))
            except APIError as e:
                st.error(str(e))


# --------------------------------------------------------------------------
# Screen 5: Evaluation
# --------------------------------------------------------------------------
def _make_judge():
    """Optional LLM-as-judge using the same key/model. Returns fluency 1-5."""
    def judge(question: str, answer: str) -> int:
        prompt = (
            "Rate the following assistant answer for clarity and helpfulness on a "
            "scale of 1 to 5 (5 = clear, fluent, directly helpful). Reply with ONLY "
            f"the digit.\n\nQuestion: {question}\nAnswer: {answer}\n\nScore (1-5):"
        )
        resp = asyncio.get_event_loop().run_until_complete(
            _llm_chat([{"role": "user", "content": prompt}])
        )
        msg = resp["message"] if isinstance(resp, dict) else resp.message
        text = (msg.get("content") if isinstance(msg, dict) else msg.content) or ""
        for ch in text:
            if ch in "12345":
                return int(ch)
        return 3
    return judge


def render_eval() -> None:
    with st.sidebar:
        st.header("Navigation")
        for label in APPROACHES:
            if st.button(label, key=f"eval_to_{label}", use_container_width=True):
                st.session_state.approach = label
                st.rerun()
        st.divider()
        if st.button("🏠 Back to landing", use_container_width=True):
            st.session_state.approach = None
            st.rerun()
        if st.button("🚪 Log out", use_container_width=True):
            _logout()
            st.rerun()

    st.title("📊 Evaluation")
    st.caption(
        "Runs a labeled question set against each backend and scores it against "
        "ground truth. Metrics: correctness, honesty (declines unanswerable "
        "questions), architecture accuracy (tool/routing/intent), JSON validity "
        "(router), latency, and robustness."
    )

    choices = ["All three"] + list(APPROACHES.keys())
    target = st.selectbox("Backend to evaluate", choices)
    use_judge = st.checkbox(
        "Also score answer fluency with an LLM judge (slower; uses the same model/key)",
        value=False,
    )
    st.info(
        "On free tier (concurrency 1) the calls run sequentially, so a full run "
        "takes a few minutes per backend.", icon="⏱️",
    )

    if st.button("Run evaluation", type="primary"):
        token = st.session_state.token
        to_run = list(APPROACHES.keys()) if target == "All three" else [target]
        judge = _make_judge() if use_judge else None
        summaries = []

        for backend in to_run:
            base_url = APPROACHES[backend]["base_url"]

            async def chat_fn(q, _b=base_url):
                return chat_for_eval(_b, token, q)

            with st.spinner(f"Evaluating {backend}… (this can take a few minutes)"):
                try:
                    summary = asyncio.run(run_eval(backend, chat_fn, judge))
                    summaries.append(summary)
                except Exception as e:
                    st.error(f"{backend}: {e}")

        if summaries:
            st.subheader("Results")
            table = []
            for s in summaries:
                table.append({
                    "Backend": s.backend,
                    "Correctness": f"{s.correctness:.0%}",
                    "Honesty": f"{s.honesty:.0%}" if s.honesty is not None else "—",
                    "Arch. accuracy": f"{s.arch_accuracy:.0%}" if s.arch_accuracy is not None else "—",
                    "JSON valid": f"{s.json_validity:.0%}" if s.json_validity is not None else "—",
                    "Avg latency": f"{s.avg_latency_s}s",
                    "Robustness": f"{s.robustness:.0%}",
                    "Avg fluency": f"{s.avg_fluency:.1f}/5" if s.avg_fluency is not None else "—",
                })
            st.dataframe(table, use_container_width=True, hide_index=True)

            for s in summaries:
                with st.expander(f"Per-question detail — {s.backend}"):
                    rows = [{
                        "ID": r.id, "Category": r.category,
                        "Correct": "✅" if r.correct else "❌",
                        "Honesty": ("✅" if r.honesty_ok else "❌") if r.honesty_ok is not None else "—",
                        "Arch": ("✅" if r.arch_metric_ok else "❌") if r.arch_metric_ok is not None else "—",
                        "Latency": f"{r.latency_s}s",
                        "Question": r.question,
                        "Answer": (r.answer[:80] + "…") if len(r.answer) > 80 else r.answer,
                        "Error": r.error or "",
                    } for r in s.results]
                    st.dataframe(rows, use_container_width=True, hide_index=True)


# --------------------------------------------------------------------------
# Router
# --------------------------------------------------------------------------
def main() -> None:
    _init_state()
    if not st.session_state.token:
        render_auth()
    elif st.session_state.approach is None:
        render_landing()
    elif st.session_state.approach == "__admin__":
        render_admin()
    elif st.session_state.approach == "__eval__":
        render_eval()
    else:
        render_chat()


if __name__ == "__main__":
    main()
