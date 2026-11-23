"""Discover cited baselines and independent publications before a review cutoff."""
from collections import Counter
import re
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

from .comparisons import STOP
from .model import ModelJSONError
from .paper import is_manuscript_title


def normalized(text):
    return " ".join(re.findall(r"[a-z0-9]+", re.sub(r"-\s+", "", text.lower())))


def terms(text):
    return [
        w.rstrip("s")
        for w in re.findall(r"[a-z0-9]+", text.lower())
        if len(w) > 2 and w not in STOP and w not in ENGLISH_STOP_WORDS
    ]


def bibliography(paper):
    for section in paper.get("sections", []):
        if re.fullmatch(
            r"(?:\d+\.?\s+)?(?:references|bibliography)", section["heading"], re.I
        ):
            pages = paper["pages"][section["start_page"] - 1 : section["end_page"]]
            body = " ".join(pages)
            body = re.split(
                r"\b(?:references|bibliography)\b", body, maxsplit=1, flags=re.I
            )[-1]
            return re.split(r"\bAPPENDIX\b|\bA\s+[A-Z][A-Z ]{7,}\b", body, maxsplit=1)[
                0
            ]
    return ""


def ranked_reference_titles(fragments, focus):
    titles = []
    for fragment in fragments:
        title = re.split(
            r",?\s+(?:19|20)\d{2}[a-z]?\b|\.\s*https?://", fragment.strip(), maxsplit=1
        )[0].strip(" ,.;")
        if not title[:1].isalpha() or title.lower().startswith(
            ("in proceedings", "we ", "in advances")
        ):
            continue
        if not 2 <= len(title.split()) <= 20 or re.search(
            r"https?://|arxiv:|\bet al\b", title, re.I
        ):
            continue
        overlap = set(terms(title)) & focus.keys()
        if overlap:
            score = sum(min(focus[t], 3) for t in overlap)
            titles.append((score, title))
    return list(
        dict.fromkeys(title for _, title in sorted(titles, key=lambda row: -row[0]))
    )


def citation_passages(paper, source, references):
    name = (source.get("first_author") or "").split()
    if not name:
        return []
    surname = name[-1]
    title = normalized(source["title"])
    pos = normalized(references).find(title)
    if pos < 0:
        return []
    reference = normalized(references)
    if normalized(surname) not in reference[max(0, pos - 650) : pos].split():
        return []
    years = set(
        re.findall(
            r"\b(?:19|20)\d{2}\b", reference[pos + len(title) : pos + len(title) + 160]
        )
    )
    years.add(source["published"][:4])
    cite = re.compile(
        r"\b"
        + re.escape(surname)
        + r"\b[^.;]{0,20}(?:et al\.)?[^.;]{0,9}?(?:"
        + "|".join(sorted(years))
        + r")\b",
        re.I,
    )
    stop = next(
        (
            s["start_page"] - 1
            for s in paper.get("sections", [])
            if re.search(r"references|bibliography", s["heading"], re.I)
        ),
        len(paper["pages"]),
    )
    return [
        dict(quote=t, page=n)
        for n, page in enumerate(paper["pages"][:stop], 1)
        for t in re.split(r"(?<!et al\.)(?<=[.!?])\s+(?=[A-Z(])", page)
        if 30 < len(t) < 650 and cite.search(t)
    ][:16]


async def discover(paper, claims, before, scholar, ask):
    references = bibliography(paper)
    study = " ".join(c["text"] for c in claims)
    focus = Counter(terms(study))
    # Prioritize the most relevant parts of long bibliographies without sending manuscript
    # text to public catalogs. Only short technical queries and verified titles leave the app.
    parts = re.split(r"(?<=[.])\s+", references)
    ranked = sorted(
        parts, key=lambda p: sum(focus[t] for t in set(terms(p))), reverse=True
    )
    try:
        plan = await ask(
            "Choose up to three relevant paper titles copied from bibliography_fragments, "
            "especially the closest direct baseline. Also propose two independent scholarly search phrases "
            "using short public technical terms for the underlying problem and method. Exclude the current paper title. "
            'Return JSON {"titles":["exact cited title"],"topics":["2-5 technical terms"]}.',
            claims=[c["text"] for c in claims],
            bibliography_fragments=ranked[:24],
            opening=paper["pages"][0][:1500],
        )
    except ModelJSONError:
        plan = {}
    reference_text = " " + normalized(references) + " "
    titles = plan.get("titles") if isinstance(plan.get("titles"), list) else []
    titles = [
        t
        for t in titles
        if isinstance(t, str)
        and len(t.split()) >= 2
        and " " + normalized(t) + " " in reference_text
    ][:3]
    # Small models sometimes propose a plausible title absent from the references.
    # Try literal reference fragments too; an external normalized title match is mandatory.
    titles = list(dict.fromkeys(titles + ranked_reference_titles(parts, focus)))[:6]
    topics = plan.get("topics") if isinstance(plan.get("topics"), list) else []
    topics = [
        t
        for t in topics
        if isinstance(t, str) and 1 < len(t.split()) <= 8 and len(t) <= 100
    ][:2]
    keywords = " ".join(w for w, _ in focus.most_common(5))
    if not topics and keywords:
        topics = [keywords]
    sources = {}
    searches = []
    for query in dict.fromkeys(titles + topics):
        cited = query in titles
        try:
            hits = await scholar(
                "search_papers", query=query, before=before, limit=6, topic=not cited
            )
        except RuntimeError:
            searches.append(
                dict(
                    query=query,
                    kind="cited title" if cited else "topic",
                    status="unavailable",
                )
            )
            continue
        matches = 0
        for hit in hits:
            title = hit.get("title", "")
            norm = normalized(title)
            if (
                not norm
                or (cited and norm != normalized(query))
                or not hit.get("published")
                or hit["published"] >= before
                or not hit.get("url")
                or is_manuscript_title(title, paper["pages"][0])
            ):
                continue
            if not hit.get("abstract") and not arxiv_id(hit["url"]):
                continue
            matches += 1
            if norm not in sources:
                sources[norm] = dict(
                    hit,
                    cited_in_manuscript=" " + norm + " " in reference_text,
                    citation_passages=citation_passages(paper, hit, references),
                )
        searches.append(
            dict(
                query=query,
                kind="cited title" if cited else "topic",
                status="complete",
                matches=matches,
            )
        )
    return list(sources.values()), searches


def arxiv_id(url):
    match = re.search(
        r"(?:arxiv\.org/(?:abs|pdf)/|10\.48550/arxiv\.)(\d{4}\.\d{4,5})(?:v\d+)?(?:$|[?#])",
        url,
        re.I,
    )
    return match[1] if match else None


def rank_sources(claim, sources):
    query = set(terms(claim))

    def relevance(source):
        anchor = max(
            (
                len(query & set(terms(x["quote"])))
                for x in source.get("citation_passages", [])
            ),
            default=0,
        )
        return (
            anchor
            + 2 * len(query & set(terms(source["title"])))
            + len(query & set(terms(source.get("abstract", ""))))
        )

    return sorted(sources, key=relevance, reverse=True)
