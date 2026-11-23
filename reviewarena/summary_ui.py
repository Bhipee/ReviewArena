"""Paper-summary workspace inside Lab meeting."""
import hashlib
import json

import streamlit as st

from .library import document, read_documents
from .paper_summary import DEFAULT_PROMPT, history, save_summary, summarize


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
    prompt = st.text_area("Summary instructions", value=DEFAULT_PROMPT, height=100)
    count = st.number_input("Number of summary examples", min_value=0, value=0, step=1)
    pairs = []
    for i in range(count):
        with st.expander(f"Example {i+1}", expanded=True):
            reference = st.file_uploader(
                "Reference paper (optional)",
                type=["pdf", "txt", "md"],
                key=f"summary-paper-{i}",
            )
            example = st.text_area("Example summary", key=f"summary-example-{i}")
            pairs.append((reference, example))
    if st.button(
        "Generate and save summary",
        disabled=not target
        or not prompt.strip()
        or any(not e.strip() for _, e in pairs),
    ):
        try:
            with st.spinner("Summarizing paper…"):
                name, digest, content = choices[target]
                doc = (
                    document(name, content)
                    if content is not None
                    else read_documents([(name, digest)])[target]
                )
                examples = []
                for upload, example in pairs:
                    item = dict(summary=example)
                    if upload is not None:
                        raw = upload.getvalue()
                        item.update(
                            name=upload.name,
                            digest=hashlib.sha256(raw).hexdigest(),
                            paper=document(upload.name, raw),
                        )
                    examples.append(item)
                output = summarize(doc, prompt, examples)
                saved = save_summary(
                    name, digest, prompt, examples, model_label, output
                )
            st.session_state["lab-summary-record"] = saved
            st.session_state["lab-summary-search"] = ""
            st.success("Summary saved to local history.")
        except Exception as exc:
            st.error(f"Could not generate and save the summary. {exc}")
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
    with st.expander("Instructions and examples used"):
        st.caption(f"Model · {record['model']}")
        st.write(record["prompt"])
        for i, e in enumerate(json.loads(record["examples"]), 1):
            st.markdown(f"**Example {i}**")
            if e.get("name"):
                st.caption(e["name"])
            st.write(e["summary"])
