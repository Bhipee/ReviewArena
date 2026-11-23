"""Compare located manuscript claims with specific passages from dated publications."""
import re
import unicodedata

from .comparisons import comparison_reviews
from .model import ModelJSONError
from .prior_work import arxiv_id, normalized, rank_sources, terms


def pdf_words(text):
    """Normalize PDF ligatures and a word broken across a line, without paraphrasing."""
    return " ".join(
        re.sub(r"(?<=\w)-\s+(?=[a-z])", "", unicodedata.normalize("NFKC", text)).split()
    )


async def compare_contributions(paper, claims, publications, before, ask, scholar=None):
    pages = paper["pages"]
    results = []
    passages = {}
    keywords = " ".join(dict.fromkeys(t for c in claims for t in terms(c["text"])))[
        :480
    ]
    for claim in claims:
        page = claim.get("page")
        text = claim.get("text", "")
        if (
            type(page) is not int
            or not 1 <= page <= len(pages)
            or not text
            or text not in pages[page - 1]
        ):
            continue
        row = dict(claim=text, page=page, status="Insufficient evidence")
        results.append(row)
        local = comparison_reviews([claim], pages[0], before, limit=4, abstracts=True)
        # Preserve one independent discovery alongside a cited baseline where available.
        external = rank_sources(text, publications)
        cited = [s for s in external if s.get("cited_in_manuscript")]
        independent = [s for s in external if not s.get("cited_in_manuscript")]
        ordered = (
            cited[:1]
            + independent[:1]
            + external
            + [dict(s, catalog="OpenReview") for s in local]
        )
        candidates = {}
        for source in ordered:
            if not source.get("published") or source["published"] >= before:
                continue
            candidates.setdefault(normalized(source["title"]), source)
        options = []
        claim_terms = set(terms(text))
        for source in list(candidates.values())[:5]:
            aid = arxiv_id(source["url"])
            if scholar and aid and aid not in passages:
                try:
                    passages[aid] = await scholar(
                        "read_prior_passages", arxiv_id=aid, keywords=keywords
                    )
                except RuntimeError:
                    passages[aid] = []
            excerpts = [
                dict(
                    quote=p["quote"],
                    page=p["page"],
                    url=p["url"],
                    kind="Paper text (v1)",
                )
                for p in passages.get(aid, [])
            ]
            # A revised abstract can describe evidence added after the cutoff.
            if not source.get("updated") or source["updated"] < before:
                excerpts.extend(
                    dict(quote=s, url=source["url"], kind="Abstract")
                    for s in re.split(r"(?<=[.!?])\s+", source.get("abstract", ""))
                    if 25 <= len(s) <= 850
                )
            anchors = source.get("citation_passages") or []
            anchor = max(
                anchors,
                key=lambda a: len(claim_terms & set(terms(a["quote"]))),
                default={},
            )
            relevant_terms = claim_terms | set(terms(anchor.get("quote", "")))
            ranked = sorted(
                excerpts,
                key=lambda e: len(relevant_terms & set(terms(e["quote"]))),
                reverse=True,
            )
            for passage in ranked[:3]:
                if len(relevant_terms & set(terms(passage["quote"]))) >= 2:
                    options.append((source, passage, anchor))
        if not options:
            continue
        choices = [
            dict(
                id=i,
                title=s["title"],
                passage=e["quote"],
                manuscript_citation=a.get("quote", ""),
            )
            for i, (s, e, a) in enumerate(options, 1)
        ]
        try:
            match = await ask(
                "Choose the single passage most directly describing the named baseline, mechanism "
                'or result relevant to the manuscript claim. Prefer a direct baseline or its technique over a general introduction. Return {"id": integer}. Use 0 if none is relevant.',
                claim=text,
                choices=choices,
            )
            index = match.get("id")
            if type(index) is not int or not 1 <= index <= len(options):
                continue
            source, evidence, anchor = options[index - 1]
            check = await ask(
                "Compare the two quoted passages only. Use shared_component for a common operation or "
                "baseline, overlapping only if both explicitly establish the same specific contribution, distinct "
                "only for an explicit technical difference, and unclear otherwise. Never infer a difference from "
                "silence. A common objective or metric alone is insufficient. Use unclear if appropriate. A comparison against a baseline is "
                "not a replication of the baseline paper. Only compare outcomes directly when the measured quantity and conditions "
                "match. For any nonzero relation, also copy current_detail and prior_detail, each "
                "an exact passage of at least four words describing the specific operations compared in the two sources. Return relation_id as one integer (0=unclear, 1=shared_component, 2=overlapping, 3=distinct) and comparison as a short sentence.",
                manuscript_claim=text,
                manuscript_citation=anchor.get("quote", ""),
                prior_title=source["title"],
                prior_passage=evidence["quote"],
            )
        except ModelJSONError:
            continue
        code = check.get("relation_id")
        relation = (
            {1: "shared_component", 2: "overlapping", 3: "distinct"}.get(code)
            if type(code) is int
            else check.get("relation")
        )
        explanation = check.get("comparison")
        row.update(
            title=source["title"],
            url=source["url"],
            prior_quote=evidence["quote"],
            prior_source=evidence["kind"],
            prior_url=evidence["url"],
            prior_page=evidence.get("page"),
            catalog=source.get("catalog"),
            cited_in_manuscript=source.get("cited_in_manuscript"),
            published=source["published"],
            citation_in_manuscript=anchor,
        )
        if (
            relation not in ("shared_component", "overlapping", "distinct")
            or not isinstance(explanation, str)
            or not explanation.strip()
        ):
            continue
        current = check.get("current_detail")
        prior = check.get("prior_detail")
        details_verified = (
            isinstance(current, str)
            and len(current.split()) >= 4
            and any(
                pdf_words(current) in pdf_words(body)
                for body in (text, anchor.get("quote", ""))
            )
            and isinstance(prior, str)
            and len(prior.split()) >= 4
            and pdf_words(prior) in pdf_words(evidence["quote"])
        )
        if relation == "distinct" and re.search(
            r"\b(?:does not|do not|did not|no mention|not explicitly|only the manuscript|not mention|not address)\b",
            explanation,
            re.I,
        ):
            continue
        if relation in ("distinct", "overlapping"):
            # A change in what an experiment measures is informative, but it cannot
            # establish a new method or a reproduction of the same contribution.
            try:
                audit = await ask(
                    "Classify the two exact excerpts independently. Return a single integer field code. "
                    "Use 1 only when both describe different concrete algorithmic steps for the same task. "
                    "Use 2 only when both make the same specific contribution under comparable conditions. "
                    "Use 3 if they measure different outcomes or hold different quantities fixed. "
                    "Use 0 when they merely share a topic, state goals, or the relation is uncertain.",
                    excerpt_a=current if details_verified else text,
                    excerpt_b=prior if details_verified else evidence["quote"],
                )
            except ModelJSONError:
                continue
            code = audit.get("code")
            if code is None and set(audit) == {"output"}:
                code = audit["output"]
            if type(code) is not int:
                continue
            if code == 3:
                row.update(
                    status="Different evaluation settings",
                    comparison="These passages measure different outcomes or hold different quantities fixed. They do not establish a like-for-like comparison.",
                )
                continue
            if code != {"distinct": 1, "overlapping": 2}[relation]:
                continue
        if not details_verified:
            continue
        row.update(status=relation, comparison=explanation.strip())
        if relation != "distinct":
            continue
        sections = [
            s["excerpt"]
            for s in paper.get("sections", [])
            if re.search(
                r"result|experiment|evaluat|theor|ablation", s["heading"], re.I
            )
        ]
        if not sections:
            continue
        try:
            validation = await ask(
                "Copy one exact clause from the manuscript that directly validates this specific "
                "difference in an experiment, ablation or theoretical result. Otherwise return an empty string. "
                "Return JSON with validation_quote.",
                difference=explanation,
                manuscript=sections[:6],
            )
        except ModelJSONError:
            continue
        quote = validation.get("validation_quote")
        if (
            isinstance(quote, str)
            and len(quote.split()) >= 5
            and any(quote in s for s in sections[:6])
        ):
            for n, body in enumerate(pages, 1):
                if quote in body:
                    row.update(validation=quote, validation_page=n)
                    break
    return results
