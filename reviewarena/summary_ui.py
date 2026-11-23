"""Paper-summary workspace inside Lab meeting."""
import hashlib
import json
import sqlite3

import streamlit as st

from .library import document, read_documents
from .paper_summary import DEFAULT_PROMPT, summarize
from .summary_store import (
    history,
    list_templates,
    load_template,
    save_summary,
    save_template,
    template_from_history,
)


def open_template(template_id):
    st.session_state["lab-summary-editor"] = load_template(template_id)
    # Streamlit uploaders cannot be populated programmatically. Start fresh widgets
    # and keep the template's original file as the default attachment for each row.
    st.session_state["lab-summary-editor-version"] = (
        st.session_state.get("lab-summary-editor-version", 0) + 1
    )


def render_examples(loaded, key):
    count = st.number_input(
        "Number of summary examples",
        min_value=0,
        value=len(loaded),
        step=1,
        key=key + "count",
    )
    examples = []
    for i in range(count):
        previous = loaded[i] if i < len(loaded) else {}
        with st.expander(f"Example {i+1}", expanded=True):
            attachment = {
                k: previous[k] for k in ("name", "digest", "content") if k in previous
            }
            if attachment:
                if attachment.get("content") is None:
                    st.warning(
                        f"Original file unavailable: {attachment['name']}. Reattach it or remove the reference."
                    )
                else:
                    st.caption(f"Saved reference · {attachment['name']}")
                if st.checkbox("Remove saved reference", key=f"{key}remove-{i}"):
                    attachment = {}
            upload = st.file_uploader(
                "Reference paper (optional)",
                type=["pdf", "txt", "md"],
                key=f"{key}paper-{i}",
            )
            if upload is not None:
                attachment = {"name": upload.name, "content": upload.getvalue()}
            summary = st.text_area(
                "Example summary",
                value=previous.get("summary", ""),
                key=f"{key}example-{i}",
            )
            examples.append(dict(attachment, summary=summary))
    return examples


def render_summary(files, selected, model_label):
    choices = {
        f"{name} [{digest[:8]}]": (name, digest, None) for name, digest in selected
    }
    for upload in files or []:
        content = upload.getvalue()
        digest = hashlib.sha256(content).hexdigest()
        choices[f"{upload.name} [{digest[:8]}]"] = (upload.name, digest, content)
    target = st.selectbox(
        "Paper to summarize",
        list(choices),
        placeholder="Upload a paper or select one from the library",
    )

    templates = dict(list_templates())
    if notice := st.session_state.pop("lab-summary-template-notice", None):
        st.success(notice)
    if missing := st.session_state.pop("lab-summary-missing-references", None):
        st.warning(
            "These older references need to be reattached: " + ", ".join(missing)
        )
    if templates:
        if pick := st.session_state.pop("lab-summary-select-template", None):
            st.session_state["lab-summary-picker"] = pick
        selected_template = st.selectbox(
            "Saved templates",
            list(templates),
            format_func=lambda i: f"{templates[i]} · #{i}",
            key="lab-summary-picker",
        )
        if st.button("Load template"):
            open_template(selected_template)

    loaded = st.session_state.get("lab-summary-editor", {})
    key = f"lab-summary-edit-{st.session_state.get('lab-summary-editor-version', 0)}-"
    if loaded:
        st.caption(f"Editing template #{loaded['id']} · {loaded['name']}")
    prompt = st.text_area(
        "Summary instructions",
        value=loaded.get("prompt", DEFAULT_PROMPT),
        height=100,
        key=key + "prompt",
    )
    examples = render_examples(loaded.get("examples", []), key)
    valid = bool(prompt.strip()) and all(e["summary"].strip() for e in examples)

    name = st.text_input(
        "Template name", value=loaded.get("name", ""), key=key + "name"
    )
    save_copy = st.button(
        "Save as new template", disabled=not valid or not name.strip()
    )
    update = loaded and st.button(
        "Update loaded template", disabled=not valid or not name.strip()
    )
    if save_copy or update:
        try:
            saved_id = save_template(
                name,
                prompt,
                examples,
                template_id=loaded["id"] if update else None,
                revision=loaded["revision"] if update else None,
            )
            open_template(saved_id)
            st.session_state["lab-summary-select-template"] = saved_id
            st.session_state[
                "lab-summary-template-notice"
            ] = f"Template saved · {name.strip()}"
            st.rerun()
        except (ValueError, OSError, sqlite3.Error) as exc:
            st.error(str(exc))

    missing_reference = any(
        e.get("name") and e.get("content") is None for e in examples
    )
    if st.button(
        "Generate and save summary",
        disabled=not target or not valid or missing_reference,
    ):
        try:
            with st.spinner("Summarizing paper…"):
                paper_name, digest, content = choices[target]
                doc = (
                    document(paper_name, content)
                    if content is not None
                    else read_documents([(paper_name, digest)])[target]
                )
                for e in examples:
                    if e.get("content") is not None:
                        e["paper"] = document(e["name"], e["content"])
                output = summarize(doc, prompt, examples)
                saved = save_summary(
                    paper_name, digest, prompt, examples, model_label, output
                )
            st.session_state["lab-summary-record"] = saved
            st.session_state["lab-summary-search"] = ""
            st.success("Summary saved to local history.")
        except Exception as exc:
            st.error(f"Could not generate and save the summary. {exc}")
    render_history()


def render_history():
    st.subheader("Summary history")
    query = st.text_input(
        "Search by paper, instructions or summary text", key="lab-summary-search"
    )
    records = history(query)
    if not records:
        st.caption("No matching summaries." if query else "No saved summaries yet.")
        return
    by_id = {r["id"]: r for r in records}
    selected_id = st.selectbox(
        "Saved summary",
        list(by_id),
        key="lab-summary-record",
        format_func=lambda i: f"#{i} · {by_id[i]['name']} · {by_id[i]['created']} UTC",
    )
    record = by_id[selected_id]
    st.markdown(record["summary"])
    if st.button(
        "Save history as new template",
        help="Copy the instructions, examples and reference papers used for this summary.",
    ):
        try:
            template_id, missing = template_from_history(selected_id)
        except (OSError, sqlite3.Error) as exc:
            st.error(f"Could not save the template. {exc}")
            return
        st.session_state["lab-summary-select-template"] = template_id
        st.session_state[
            "lab-summary-template-notice"
        ] = f"Created template #{template_id} from summary #{selected_id}."
        st.session_state["lab-summary-missing-references"] = missing
        st.rerun()
    with st.expander("Instructions and examples used"):
        st.caption(f"Model · {record['model']}")
        st.write(record["prompt"])
        for i, e in enumerate(json.loads(record["examples"]), 1):
            st.markdown(f"**Example {i}**")
            if e.get("name"):
                st.caption(e["name"])
            st.write(e["summary"])
