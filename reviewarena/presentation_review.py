"""Observable writing, typesetting and figure evidence from the submitted PDF."""
import asyncio
import base64
import os
import hashlib
import re

import pymupdf
import requests

from .model import ModelJSONError, generate, local_endpoint

# Match printed reference failures. The reviewer still checks the surrounding sentence
# because a paper about typesetting may intentionally show one of these strings.
UNRESOLVED = re.compile(r"(?:\b(?:fig(?:ure)?|table|eq(?:uation)?|sec(?:tion)?|appendix)\.?\s*\(?\?\?|\[\s*\?+\s*\]|\\(?:cite[pt]?|eqref|ref)\{[^}]+\})", re.I)
CAPTION = re.compile(r"\b(Figure|Fig\.|Table)\s+(\d+[a-z]?)\s*[:.](?=\s)", re.I)


def presentation_sources(paper):
    rows = []
    seen = set()

    def add(kind, page, text, label="", **details):
        if not text or (kind, page, text) in seen:
            return
        seen.add((kind, page, text))
        rows.append(dict(id=f"presentation-{len(rows)+1}", kind=kind, page=page, quote=text, label=label, **details))

    for page, text in enumerate(paper["pages"], 1):
        for match in UNRESOLVED.finditer(text):
            add("printed reference to check", page, text[max(0,match.start()-60):match.end()+80])
            if len(rows) >= 6:
                break
        if len(rows) >= 6:
            break
    captions = list(paper.get("captions", ()))
    # Include captions split across PDF blocks, even when other captions were parsed correctly.
    known = {(c["page"],c["label"].lower().replace("fig.", "figure")) for c in captions}
    for page, text in enumerate(paper["pages"], 1):
        for match in CAPTION.finditer(text):
            label = ("Table" if match[1].lower()=="table" else "Figure") + " " + match[2]
            if (page,label.lower()) not in known:
                captions.append(dict(page=page, label=label, quote=text[match.start():match.end()+190]))
                known.add((page,label.lower()))
    captions.sort(key=lambda row:row["page"])
    for kind in ("figure", "table"):
        matches = [c for c in captions if c["label"].lower().startswith(kind[:3])]
        for c in matches[:3]:
            add("caption", c["page"], c["quote"][:650], c["label"])
    for table in paper.get("tables", ())[:2]:
        text = paper["pages"][table["page"]-1]
        labels = list(dict.fromkeys(c for c in table["cells"][:20] if re.search(r"[A-Za-z]", c) and c in text))
        if labels:
            add("extracted table label", table["page"], labels[0], table["caption"][:100],
                nearby_labels=labels[:8])
    return rows


def figure_pages(rows, page_count):
    selected = []
    for kind in ("fig", "tab"):
        for row in rows:
            if row["kind"]=="caption" and row["label"].lower().startswith(kind) and row["page"] not in selected:
                selected.append(row["page"])
                break
    return (selected or [1])[:min(2,page_count)]


def page_images(pdf_bytes, numbers):
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        images = []
        for n in numbers:
            pix = doc[n-1].get_pixmap(dpi=125, alpha=False)
            encoded = base64.b64encode(pix.tobytes("jpeg", jpg_quality=85)).decode("ascii")
            images.append("data:image/jpeg;base64," + encoded)
        return images


def inspect_visuals(pdf_bytes, numbers):
    images = page_images(pdf_bytes, numbers)
    return generate(
        "Inspect the attached rendered manuscript pages in the listed order. Check visual legibility, labels, units, "
        "legends, figure and table design, equations and typesetting. Give at most three concrete observations "
        "about visible items with their page number, named element and what it helps or prevents a reader from "
        "understanding. Include positive evidence when warranted. Never infer a TeX source or compiler error. "
        'Return {"observations":[{"page":1,"element":"Figure 2","observation":"..."}]}.',
        {"page_numbers_in_image_order":numbers}, images=images)


async def presentation_review(paper, pdf_bytes):
    rows = presentation_sources(paper)
    endpoint = os.getenv("REVIEWARENA_API_URL","http://127.0.0.1:8766/v1")
    flag = os.getenv("REVIEWARENA_VISION","auto").lower()
    use_images = flag in ("1", "true") or (flag == "auto" and not local_endpoint(endpoint))
    mode = "PDF text and captions only"
    inspected = []
    if pdf_bytes and use_images:
        if paper.get("hash") and hashlib.sha256(pdf_bytes).hexdigest()!=paper["hash"]:
            raise ValueError("Rendered pages must come from the reviewed PDF.")
        numbers = figure_pages(rows,len(paper["pages"]))
        try:
            result = await asyncio.to_thread(inspect_visuals, pdf_bytes, numbers)
        except (requests.RequestException, ModelJSONError):
            mode = "PDF text and captions only (image review unavailable)"
        else:
            observations=result.get("observations")
            if isinstance(observations,list):
                inspected = numbers
                mode = "Rendered PDF pages and extracted text"
            for row in observations if isinstance(observations,list) else []:
                if not isinstance(row,dict) or type(row.get("page")) is not int or row["page"] not in numbers:
                    continue
                element, note = row.get("element"),row.get("observation")
                if isinstance(element,str) and element.strip() and isinstance(note,str) and note.strip():
                    rows.append(dict(id=f"visual-{len(rows)+1}",kind="visual observation",
                                     page=row["page"],label=element,quote=note))
    return dict(mode=mode, inspected_pages=inspected, sources=rows)
