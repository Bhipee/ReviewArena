"""Workspace styling and controls for loading saved demonstration results."""
import streamlit as st
from .demos import save_demo


def workspace_style():
    st.html("""<style>
        .stApp {
            --ra-accent: #226254;
            --ra-line: color-mix(in srgb, var(--text-color) 18%, transparent);
        }
        [data-testid="stMainBlockContainer"] {
            max-width: 78rem; padding-top: 3.2rem; padding-bottom: 4rem;
        }
        [data-testid="stSidebar"] {border-right: 1px solid var(--ra-line)}
        [data-testid="stHeadingWithActionElements"] :is(h1,h2,h3) {
            letter-spacing: -.025em; line-height: 1.22; overflow-wrap: anywhere;
        }
        [data-testid="stHeadingWithActionElements"] h1 {font-size: clamp(2rem, 3.7vw, 3.05rem)}
        .st-key-brand p {font-size: 1.18rem; font-weight: 730; letter-spacing: -.03em}
        .st-key-demo-panel details {
            border-color: color-mix(in srgb, #756493 54%, var(--ra-line));
        }
        .st-key-demo-panel [data-testid="stExpander"] summary {
            background: color-mix(in srgb, #9a86b9 8%, transparent);
        }
        [data-testid="stTabs"] [role="tablist"] {gap: .45rem; border-bottom: 1px solid var(--ra-line)}
        [data-testid="stTabs"] [role="tab"] {padding-inline: .85rem; white-space: nowrap}
        [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
            color: var(--text-color); background: color-mix(in srgb, #428975 12%, transparent);
            border-radius: .45rem .45rem 0 0;
        }
        [class*="st-key-weakness-card-"] {border-inline-start: 3px solid #ad7831}
        .ra-finding {margin: 0; font-size: 1.05rem; font-weight: 600; line-height: 1.55; overflow-wrap: anywhere}
        .ra-excerpt {margin: 0; padding: .7rem 1rem; border-inline-start: 2px solid #648b84;
            background: color-mix(in srgb, #648b84 7%, transparent); overflow-wrap: anywhere}

        .st-key-workspace-inputs [data-testid="stFileUploaderDropzone"] {
            border: 1.5px dashed color-mix(in srgb, #357766 65%, var(--ra-line));
            background: color-mix(in srgb, #488e79 5%, transparent); padding: 1.15rem;
        }
        .st-key-decision {border-inline-start: 4px solid var(--ra-accent)}
        .st-key-decision:has(.st-key-reject) {border-inline-start-color: #bd574d}
        [data-testid="stBaseButton-primary"] {background: #226254; border-color: #226254; color: white}
        [data-testid="stBaseButton-primary"]:hover {background: #194f43; border-color: #194f43}
        @media (max-width: 700px) {
            [data-testid="stMainBlockContainer"] {padding: 3.5rem 1rem 2rem}
        }
    </style>""")


def action_buttons(label, key, *, demo_panel, demo_label, available, disabled=False, primary=False, live_panel=st):
    live = live_panel.button(label, key="live-" + key, type="primary" if primary else "secondary", disabled=disabled)
    demo = demo_panel.button(
        demo_label, key="demo-" + key, icon=":material/history:",
        disabled=disabled or not available,
        help="Load the saved result for these inputs without calling the model."
        if available else "No saved result for the current inputs.",
    )
    return live, demo


def remember_demo(action, inputs, result):
    try:
        save_demo(action, inputs, result)
    except OSError as exc:
        st.warning(f"The result is available in this session. Saving its demo failed: {exc}")
