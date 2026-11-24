"""Paper-summary workspace inside Lab meeting."""
import hashlib
import json
import sqlite3

import streamlit as st

from .demo_ui import action_buttons, remember_demo
from .demos import demo_path, fingerprint, load_demo, summary_inputs
from .kb import DATA
from .library import document, read_documents, saved_source
from .summary_store import saved_reference
from .named_demo_ui import save_current_demo
from .paper_summary import DEFAULT_PROMPT, summarize
from .summary_store import (
    history,
    matching_summary,
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
        with st.container(border=True):
            st.markdown(f"**Example {i+1}**")
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


def render_summary(files, selected, model_label, demo_inputs, demo_actions, save_panel):
    choices = {
        f"{name} [{digest[:8]}]": (name, digest, None) for name, digest in selected
    }
    for upload in files or []:
        content = upload.getvalue()
        digest = hashlib.sha256(content).hexdigest()
        choices[f"{upload.name} [{digest[:8]}]"] = (upload.name, digest, content)
    public_pdf = DATA / "iclr2023/5NTt8GFjUHkr.pdf"
    if public_pdf.is_file() and demo_inputs.checkbox("Use the public Auto-CoT paper"):
        raw = public_pdf.read_bytes()
        choices = {
            "Auto-CoT · public example": (
                public_pdf.name,
                hashlib.sha256(raw).hexdigest(),
                raw,
            ),
            **choices,
        }
    summary_tab, templates_tab, history_tab = st.tabs(["Summary", "Instructions and templates", "History"])
    target = summary_tab.selectbox(
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
    with templates_tab:
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
    inputs = summary_inputs(choices[target][1], prompt, examples) if target else None
    preview_key = "summary-preview-" + fingerprint(inputs)
    archived = matching_summary(*inputs) if inputs else None
    has_local = inputs is not None and demo_path("summary", inputs).is_file()
    run, demo = action_buttons(
        "Generate and save summary",
        "paper-summary",
        demo_panel=demo_actions, demo_label="Load saved paper summary", live_panel=summary_tab, primary=True,
        available=archived is not None or has_local,
        disabled=not target or not valid or missing_reference,
    )
    if demo:
        st.session_state[preview_key] = (
            archived if archived is not None else load_demo("summary", inputs)
        )
    if run:
        st.session_state.pop(preview_key, None)
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
            remember_demo("summary", inputs, output)
            st.session_state["lab-summary-record"] = saved
            st.session_state["lab-summary-search"] = ""
            st.session_state[
                "lab-summary-template-notice"
            ] = "Summary saved to local history."
            st.rerun()
        except Exception as exc:
            st.error(f"Could not generate and save the summary. {exc}")
    if preview := st.session_state.get(preview_key):
        summary_tab.caption("Demo · saved paper summary")
        summary_tab.markdown(preview)
    elif archived:
        summary_tab.caption("Saved summary for these instructions")
        summary_tab.markdown(archived)
    with history_tab:
        record = render_history()

    current = None
    if preview or archived:
        title, digest, content = choices[target]
        current = dict(
            mode="summary", title=title, summary=preview or archived, prompt=prompt,
            examples=[{k: e[k] for k in ("name", "summary") if k in e} for e in examples],
        )
    historical = None
    if record:
        history_examples = json.loads(record["examples"])
        history_inputs = summary_inputs(record["digest"], record["prompt"], history_examples)
        if current is None or inputs != history_inputs or current["summary"] != record["summary"]:
            historical = dict(mode="summary", title=record["name"], summary=record["summary"],
                              prompt=record["prompt"], examples=history_examples, model=record["model"])

    if current is None and historical is None:
        save_current_demo(save_panel, "Lab meeting")
        return
    use_history = current is None
    if current and historical:
        use_history = save_panel.radio("Summary to save", ["Current summary", "Selected history entry"],
                                       horizontal=True) == "Selected history entry"
    if use_history:
        save_panel.caption(f"From summary history · {historical['title']}")
    view = historical if use_history else current

    def attachments():
        if use_history:
            main = saved_source(record["digest"])
            references = [saved_reference(e["digest"]) if e.get("digest") else None for e in history_examples]
        else:
            main = content if content is not None else saved_source(digest)
            references = [e.get("content") for e in examples]
        files = {f"example-{i}": raw for i, raw in enumerate(references, 1) if raw is not None}
        if main is not None:
            files["paper"] = main
        return files

    save_current_demo(save_panel, "Lab meeting", view["title"], view, attachments)


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
    with st.container(border=True):
        st.markdown("**Instructions used for this summary**")
        st.caption(f"Model · {record['model']}")
        st.write(record["prompt"])
        for i, e in enumerate(json.loads(record["examples"]), 1):
            st.markdown(f"**Example {i}**")
            if e.get("name"):
                st.caption(e["name"])
            st.write(e["summary"])
    return record


def render_saved_summary(view, files):
    st.subheader(view["title"])
    summary, instructions = st.tabs(["Summary", "Instructions and examples"])
    summary.markdown(view["summary"])
    if "paper" in files:
        summary.download_button("Download source paper", files["paper"], file_name=view["title"], on_click="ignore")
    instructions.markdown("**Summary instructions**")
    instructions.write(view["prompt"])
    if view.get("model"):
        instructions.caption(f"Model · {view['model']}")
    for i, example in enumerate(view["examples"], 1):
        instructions.markdown(f"**Example {i}**")
        if example.get("name"):
            instructions.caption(example["name"])
        instructions.write(example["summary"])
        if (raw := files.get(f"example-{i}")) is not None:
            instructions.download_button("Download reference paper", raw, file_name=example["name"],
                                         key=f"demo-summary-reference-{i}", on_click="ignore")
