"""Save and replay a named workspace result without reconstructing its inputs."""
import sqlite3

import streamlit as st

from .named_demos import list_named_demos, load_named_demo, save_named_demo


def demo_library(panel, workspace):
    """Offer playback even before the user supplies any workspace inputs."""
    selected_key = "named-picker-" + workspace
    active_key = "named-replay-" + workspace
    if notice := st.session_state.pop("named-notice-" + workspace, None):
        panel.success(f"Saved “{notice[1]}” to this workspace.")
        st.session_state[selected_key] = notice[0]
        st.session_state.pop("named-title-" + workspace, None)
    try:
        entries = list_named_demos(workspace)
        if entries:
            labels = {i: f"{name} · {created} UTC · #{i}" for i, name, created in entries}
            chosen = panel.selectbox("Saved demos", list(labels), format_func=labels.get, key=selected_key)
            if panel.button("Load saved demo", key="named-load-" + workspace, icon=":material/history:"):
                st.session_state[active_key] = load_named_demo(workspace, chosen)
    except (OSError, ValueError, sqlite3.Error) as exc:
        panel.error(f"Could not read the demo library. {exc}")
    active = st.session_state.get(active_key)
    if active:
        st.caption(f"Playing saved demo · {active['name']}")
        if st.button("Exit saved demo", key="named-exit-" + workspace):
            del st.session_state[active_key]
            st.rerun()
    return active


def save_current_demo(panel, workspace, title="", view=None, files=None):
    """Evaluate the attachment provider only when the user explicitly saves."""
    available = view is not None
    name = ""
    if available:
        name = panel.text_input("Demo name", placeholder=title, key="named-title-" + workspace)
    if panel.button("Save current for demo", key="named-save-" + workspace,
                    icon=":material/bookmark_add:", disabled=not available,
                    help="Save the displayed results and their source material on this computer."
                    if available else "Complete or load a result first."):
        try:
            name = name.strip() or title
            demo_id = save_named_demo(workspace, name, view, files() if files else {})
        except (OSError, ValueError, sqlite3.Error) as exc:
            panel.error(f"Could not save this demo. {exc}")
        else:
            st.session_state["named-notice-" + workspace] = (demo_id, name)
            st.rerun()
