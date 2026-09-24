from __future__ import annotations

import time

import streamlit as st

from agents.chat_agent import (
    SAFE_FALLBACK,
    SAFE_FALLBACK_GENERAL,
    findings_messages,
    general_messages,
    stream_reply,
)
from graph.workflow import run_analysis
from models.schemas import AnalysisRun
from ui.chat import (
    ASSISTANT_AVATAR,
    BRAND_ICON,
    BRAND_MARK,
    FOLLOW_UP_CHIPS,
    START_CHIPS,
    STEP_NOTES,
    USER_AVATAR,
    chips,
    greeting,
    render_message,
)
from utils.config import load_settings
from utils.cost_tracker import CostTracker
from utils.errors import UserFacingError
from utils.openai_client import OpenAIService

st.set_page_config(page_title="ClauseLens", page_icon=BRAND_ICON, layout="centered")
st.session_state.setdefault("messages", [])
st.session_state.setdefault("results", {})
st.session_state.setdefault("latest_run", None)
st.session_state.setdefault("legal_marks", [])
st.session_state.setdefault("pending", None)


def reset_chat() -> None:
    st.session_state.messages = []
    st.session_state.results = {}
    st.session_state.latest_run = None
    st.session_state.legal_marks = []
    st.session_state.pending = None


def pick_start(value: str) -> None:
    st.session_state.pending = {"action": "ask", "text": START_CHIPS[value].split(": ", 1)[-1]}


def pick_follow_up(question: str) -> None:
    st.session_state.pending = {"action": "ask", "text": question}


def add(role: str, kind: str, content: str = "", **extra) -> None:
    st.session_state.messages.append({"role": role, "kind": kind, "content": content, **extra})


@st.cache_resource(max_entries=1)
def shared_client() -> OpenAIService:
    return OpenAIService(load_settings())


def client_or_error() -> tuple[OpenAIService | None, str]:
    try:
        client = shared_client()
        return client, client.model
    except UserFacingError as exc:
        st.error(exc.message)
        add("assistant", "error", exc.message)
        return None, ""


def analyze(filename: str, data: bytes) -> bool:
    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        client, model = client_or_error()
        if client is None:
            return False
        started = time.perf_counter()
        with st.status(f":shimmer[Reviewing {filename}]", type="compact") as status:

            def on_step(label: str, phase: str = "complete") -> None:
                note = STEP_NOTES.get(label, "Working…")
                try:
                    if phase == "running":
                        with st.status(label, type="step", state="running"):
                            st.caption(note)
                        return
                    with st.status(label, type="step", state="complete"):
                        st.caption(note)
                except Exception:
                    return

            try:
                result = run_analysis(data, filename, llm=client, model_name=model, on_step=on_step)
            except UserFacingError as exc:
                status.update(label="Analysis stopped", state="error")
                st.error(exc.message)
                add("assistant", "error", exc.message)
                return False
            seconds = int(time.perf_counter() - started)
            status.update(label=f"Reviewed in {seconds} seconds", state="complete")
    st.session_state.results[result.run_id] = result.model_dump()
    st.session_state.latest_run = result.run_id
    add("assistant", "report", run_id=result.run_id)
    return True


def ask(question: str) -> None:
    latest = st.session_state.latest_run
    history = st.session_state.messages[:-1]
    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        client, _model = client_or_error()
        if client is None:
            return
        tracker = CostTracker(model=client.chat_model, run_id=f"{latest or 'general'}-chat")
        if latest is None:
            system, user = general_messages(question, history)
            fallback = SAFE_FALLBACK_GENERAL
        else:
            result = AnalysisRun.model_validate(st.session_state.results[latest])
            system, user = findings_messages(question, result, history)
            fallback = SAFE_FALLBACK
        placeholder = st.empty()
        placeholder.markdown(":gray[Thinking…]")
        reply = ""
        for reply in stream_reply(client, tracker, system, user, fallback):
            placeholder.markdown(reply + " ▌")
        placeholder.markdown(reply)
        add("assistant", "text", reply)


with st.sidebar:
    st.markdown(f"### {BRAND_MARK} ClauseLens")
    st.caption("Understand your agreement before you sign.")
    st.button("New chat", icon=":material/add:", on_click=reset_chat, width="stretch")
    st.space("small")
    st.caption(
        "ClauseLens compares your agreement with a versioned comparison-standard library. "
        "It does not make a signing decision, and it is not legal advice."
    )
    st.caption("Uploaded documents are treated as untrusted data. Instructions inside them are never followed.")
    st.divider()
    st.caption(":material/dark_mode: Light / Dark theme in ⋮ menu")

if not st.session_state.messages:
    greeting()
    chips(START_CHIPS, "start", pick_start)

for message in st.session_state.messages:
    render_message(message, st.session_state.results, st.session_state.latest_run)

last = st.session_state.messages[-1] if st.session_state.messages else None
if last and last.get("kind") == "report":
    chips(FOLLOW_UP_CHIPS, "follow", pick_follow_up)

prompt = st.chat_input(
    "Attach an agreement PDF or ask about the results",
    accept_file=True,
    file_type=["pdf"],
    submit_mode="disable",
)

pending = st.session_state.pending
st.session_state.pending = None

if prompt:
    files = prompt.files if "files" in prompt and prompt.files else []
    text = (prompt.text or "").strip()
    if files:
        upload = files[0]
        add("user", "file", upload.name, text=text)
        render_message(st.session_state.messages[-1], {}, None)
        if analyze(upload.name, upload.getvalue()) and text:
            ask(text)
    elif text:
        add("user", "text", text)
        render_message(st.session_state.messages[-1], {}, None)
        ask(text)
    st.rerun()
elif pending:
    add("user", "text", pending["text"])
    render_message(st.session_state.messages[-1], {}, None)
    ask(pending["text"])
    st.rerun()
