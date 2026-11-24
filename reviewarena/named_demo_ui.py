"""Save and replay a named workspace result without reconstructing its inputs."""
import sqlite3

import streamlit as st

from .named_demos import delete_named_demo, list_named_demos, load_named_demo, save_named_demo


def demo_library(panel, workspace):
    """Offer playback even before the user supplies any workspace inputs."""
    selected_key = "named-selected-" + workspace
    pending_key = "named-pending-delete-" + workspace
    active_key = "named-replay-" + workspace
    if notice := st.session_state.pop("named-notice-" + workspace, None):
        panel.success(f"Saved “{notice[1]}” to this workspace.")
        st.session_state[selected_key] = notice[0]
        st.session_state.pop("named-title-" + workspace, None)
    try:
        entries = list_named_demos(workspace)
        ids = {i for i, _, _ in entries}
        if (st.session_state.get(active_key) or {}).get("id") not in ids:
            st.session_state.pop(active_key, None)
        if st.session_state.get(pending_key) not in ids:
            st.session_state.pop(pending_key, None)
        panel.markdown("**Saved demos**")
        if entries:
            if st.session_state.get(selected_key) not in ids:
                st.session_state[selected_key] = entries[0][0]
            chosen = st.session_state[selected_key]
            options = panel.container(key="saved-demo-options", height=300 if len(entries) > 5 else "content")
            for demo_id, name, created in entries:
                select, remove = options.columns([8, 1], gap="small")
                label = f"{name} · {created} UTC · #{demo_id}"
                select.button(label, key=f"named-option-{workspace}-{demo_id}", use_container_width=True,
                              icon=":material/radio_button_checked:" if demo_id == chosen else ":material/radio_button_unchecked:",
                              on_click=st.session_state.__setitem__, args=(selected_key, demo_id))
                remove.button("×", key=f"named-remove-{workspace}-{demo_id}", help=f"Delete {name} (#{demo_id})",
                              on_click=st.session_state.__setitem__, args=(pending_key, demo_id))
                if st.session_state.get(pending_key) == demo_id:
                    options.caption(f"Delete “{name}” (#{demo_id}) from this workspace?")
                    confirm, cancel = options.columns(2)
                    if confirm.button("Delete demo", key=f"named-confirm-{workspace}-{demo_id}"):
                        delete_named_demo(workspace, demo_id)
                        st.session_state.pop(pending_key, None)
                        st.rerun()
                    cancel.button("Cancel", key=f"named-cancel-{workspace}-{demo_id}",
                                  on_click=st.session_state.pop, args=(pending_key, None))
            if panel.button("Load saved demo", key="named-load-" + workspace, icon=":material/history:"):
                st.session_state[active_key] = load_named_demo(workspace, chosen)
        else:
            st.session_state.pop(selected_key, None)
            panel.caption("No saved demos in this workspace.")
    except (OSError, ValueError, sqlite3.Error) as exc:
        panel.error(f"Could not access the demo library. {exc}")
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
