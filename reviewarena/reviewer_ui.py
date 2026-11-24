"""Reader-facing reviewer findings, with unmodified source fields available for inspection."""
from html import escape

import streamlit as st


WEAKNESS_FIELDS = ("weaknesses", "weakness", "weaknesss")


def review_items(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def statement(item, fields):
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for field in fields:
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def weakness_cards(report):
    cards = {}
    for field in WEAKNESS_FIELDS:
        for item in review_items(report.get(field)):
            issue = statement(item, ("issue", "weakness", "text", "description"))
            if not issue:
                continue
            card = cards.setdefault(issue, {"issue": issue, "pages": [], "sources": []})
            if not isinstance(item, dict):
                continue
            for page in review_items(item.get("pages")):
                if type(page) is int and page > 0 and page not in card["pages"]:
                    card["pages"].append(page)
            for source in review_items(item.get("evidence")):
                if not isinstance(source, dict):
                    continue
                quote = statement(source, ("quote", "text"))
                page = source.get("page")
                page = page if type(page) is int and page > 0 else None
                url = source.get("url")
                url = url if isinstance(url, str) and url.startswith(("https://", "http://")) else None
                if not quote or not (page or url):
                    continue
                excerpt = dict(page=page, title=source.get("title") or "Prior publication", url=url, quote=quote)
                if excerpt not in card["sources"]:
                    card["sources"].append(excerpt)
    return list(cards.values())


def source_label(source):
    return f"Manuscript · p. {source['page']}" if source["page"] else str(source["title"])


def render_weaknesses(report, prefix):
    cards = weakness_cards(report)
    st.subheader("Weaknesses")
    if not cards:
        st.caption("This review contains no recorded weakness statement.")
    for i, card in enumerate(cards):
        with st.container(border=True, key=f"weakness-card-{prefix}-{i}"):
            st.html(f'<p class="ra-finding">{escape(card["issue"])}</p>')
            sources = card["sources"]
            if sources:
                if len(sources) > 1:
                    selected = st.selectbox(
                        "Supporting passage", range(len(sources)),
                        format_func=lambda n, options=sources: f"{n+1} of {len(options)} · {source_label(options[n])}",
                        key=f"weakness-source-{prefix}-{i}",
                    )
                    source = sources[selected]
                else:
                    source = sources[0]
                    st.caption(source_label(source))
                st.html(f'<blockquote class="ra-excerpt">{escape(source["quote"])}</blockquote>')
                if source["url"]:
                    st.link_button(source["title"], source["url"])
            else:
                pages = ", ".join(map(str, card["pages"]))
                st.caption((f"Reviewer cites p. {pages}. " if pages else "") + "No source passage attached.")
