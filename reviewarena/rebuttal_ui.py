"""Display the sources and experiments behind a point-by-point author reply."""
import json
from itertools import groupby

import streamlit as st

from .api import experiment_checklist
from .demos import fingerprint
from .paper import highlight


def show_evidence(content,ev):
    st.caption(f"Manuscript evidence · p. {ev['page']}")
    if ev.get("reason"):st.write(ev["reason"])
    st.write(ev['quote'])
    st.image(highlight(content,ev['page'],ev['quote']),width=600)


def render_mentioned_works(reading):
    st.subheader("Works cited by the reviewer")
    st.caption("Publication cutoff · "+reading["before"])
    if not reading["works"]:
        st.caption("No named publication was found in this comment.")
    for work in reading["works"]:
        with st.container(border=True):
            st.markdown("**"+work["mention"]+"**")
            record=work["catalog_record"]
            if record:
                st.link_button(record["title"],record["url"],icon=":material/open_in_new:")
                st.caption("Published "+record["published"])
            else:
                st.caption("Publication unverified · "+work["query"])
            for citation in work["bibliography"]:
                st.caption(f"Bibliography entry in your manuscript · p. {citation['page']}")
                st.write(citation["quote"])
            if not work["comparison_passages"]:
                st.caption("No matching comparison-table caption found in the manuscript.")


def comparison_captions(reading):
    matches={}
    for work in reading["works"]:
        for passage in work["comparison_passages"]:
            mentions=matches.setdefault((passage["page"],passage["quote"]),[])
            if work["mention"] not in mentions:
                mentions.append(work["mention"])
    return [dict(page=page,quote=quote,reason="Comparison table · "+", ".join(mentions))
            for (page,quote),mentions in matches.items()]


def select_point(responses,field,key):
    points={n:r for n,r in enumerate(responses,1) if r.get(field)}
    if not points:
        return None
    def label(n):
        return f"Reviewer point {n}"
    if len(points)>1:
        number=st.selectbox("Reviewer point",list(points),format_func=label,key=key)
    else:
        number=next(iter(points))
        st.caption(label(number))
    st.write(points[number]["critique"])
    return number,points[number][field]


def render_manuscript_evidence(content,responses,reading,key):
    st.subheader(":material/find_in_page: Evidence from your manuscript")
    selected=select_point(responses,"evidence","rebuttal-evidence-"+key)
    captions=comparison_captions(reading) if reading else []
    if selected:
        for passage in selected[1]:
            with st.container(border=True):
                show_evidence(content,passage)
    elif responses or not captions:
        st.caption("No manuscript passage was linked to a reviewer point." if responses else
                   "No matching manuscript comparison passage was found.")
    if captions:
        st.subheader("Comparison tables in your manuscript")
        for passage in captions:
            with st.container(border=True):
                show_evidence(content,passage)


def render_historical_replies(responses,key):
    st.subheader(":material/forum: Past OpenReview exchanges")
    selected=select_point(responses,"history","rebuttal-history-"+key)
    if not selected:
        st.caption("No historical reply was linked to these comments.")
        return
    number,history=selected
    index=0
    if len(history)>1:
        index=st.selectbox("Historical paper and reply",range(len(history)),
                           format_func=lambda i:f"{i+1}. {history[i]['title']}",key=f"{key}-reply-example-{number}")
    h=history[index]
    with st.container(border=True):
        st.markdown("**"+h["title"]+"**")
        has_reply_link=h.get("reply_id") and h.get("paper_id")
        links=st.columns(2) if has_reply_link else [st]
        links[0].link_button("Open reviewer comment",h["source"],icon=":material/open_in_new:")
        if has_reply_link:
            links[1].link_button("Open author reply",f"https://openreview.net/forum?id={h['paper_id']}&noteId={h['reply_id']}",icon=":material/open_in_new:")
        try:reply=json.loads(h["reply"])
        except (ValueError,TypeError):reply=h["reply"]
        if isinstance(reply,dict):
            reply=reply.get("Comment") or reply.get("Response") or reply
        st.markdown("**Historical author reply**")
        st.write(reply)
        if h.get("reply_strategy_quote"):
            st.caption("Author wording for the response strategy")
            st.write(h["reply_strategy_quote"])
        if h.get("resolution_quote") and type(h.get("resolved")) is bool:
            outcome="resolved" if h["resolved"] else "unresolved"
            st.caption("Reviewer's follow-up · "+outcome)
            st.write(h["resolution_quote"])


def render_experiments(steps,key):
    st.subheader("Experiment checklist")
    st.html("""<style>
      [class*="st-key-experiment-task-"] [data-testid="stCheckbox"] label p {font-weight: 600; line-height: 1.5}
      [class*="st-key-experiment-task-1-"] {border-inline-start: 3px solid #ad7831}
      [class*="st-key-experiment-task-2-"] {border-inline-start: 3px solid #587ba2}
    </style>""")
    progress=st.empty()
    state_key="rebuttal-completed-"+key
    previous=st.session_state.get(state_key,set())
    completed=set()
    labels={1:("High priority","orange"),2:("Medium priority","blue"),
            3:("Low priority","gray"),4:("Priority unassigned","gray")}
    def priority(step):
        return {"1":1,"high":1,"2":2,"medium":2,"3":3,"low":3}.get(str(step.get("priority")).strip().lower(),4)
    for rank,items in groupby(steps,key=priority):
        label,color=labels[rank]
        st.badge(label,color=color,icon=":material/flag:")
        for step in items:
            number=step["reviewer_point"]
            experiment=step["experiment"]
            identifier=fingerprint([number,experiment])
            with st.container(border=True,key=f"experiment-task-{rank}-{number}"):
                if st.checkbox(experiment,value=identifier in previous,key=f"{key}-experiment-{identifier}"):
                    completed.add(identifier)
                st.caption(f"Reviewer point {number}")
                st.markdown(f":material/schedule: **Estimated effort** · {step.get('effort') or 'To estimate'}")
    st.session_state[state_key]=completed
    progress.progress(len(completed)/len(steps),text=f"{len(completed)} of {len(steps)} experiments complete")


def experiments_by_reviewer_point(responses):
    return experiment_checklist([{"answer":dict(r["answer"],reviewer_point=n)} for n,r in enumerate(responses,1)])
