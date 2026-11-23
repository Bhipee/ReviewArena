"""Adjacent live and local-demo actions."""
import streamlit as st
from .demos import save_demo


def action_buttons(label, key, *, available, disabled=False, primary=False):
    main, saved, _ = st.columns([3, 1, 6])
    live = main.button(
        label,
        key="live-" + key,
        type="primary" if primary else "secondary",
        disabled=disabled,
    )
    demo = saved.button(
        "Demo",
        key="demo-" + key,
        disabled=disabled or not available,
        help="Show the saved local result."
        if available
        else "Run this action once with these inputs to prepare its demo.",
    )
    return live, demo


def remember_demo(action, inputs, result):
    try:
        save_demo(action, inputs, result)
    except OSError as exc:
        st.warning(
            f"The result is available in this session. Saving its demo failed: {exc}"
        )
