"""Scientific questions and source selection for manuscript reviewers."""
import re
from .embedding import embed
from .verifier import passages

THEORY = "Theory and assumptions"
EXPERIMENTS = "Experiments and evaluation"
CLARITY = "Clarity and reproducibility"

PRESENTATION = "Writing, typesetting and visuals"
INNOVATION = "Originality and research value"

BRIEFS = {
    THEORY: (
        "Which inference does the central claim require, and under what premise is it justified? "
        "Lead with a specific definition, mechanism or assumption and trace its consequence. "
        "For an empirical paper, examine the inference from observation to explanation or generalization. "
        "A formal proof is only relevant when the paper claims a guarantee."
    ),
    EXPERIMENTS: (
        "Which comparison actually tests the claim, and what does its design establish? "
        "Lead with a particular control, split, baseline, metric, uncertainty estimate or ablation. "
        "Explain how it supports or limits an inference about performance. A list of scores alone is insufficient."
    ),
    CLARITY: (
        "Could another group implement a crucial step and reproduce the reported measurement? "
        "Lead with a concrete decision the implementer must make and say which instruction, setting or artifact "
        "settles it or leaves it ambiguous. Check the appendix before claiming a detail is missing. "
        "Clear instructions can be a strength. Reporting an accuracy gain says little about reproducibility."
    ),
    PRESENTATION: (
        "Can a reader understand the paper's argument, notation, figures and tables as presented? "
        "Check scientific writing for precision and organization, printed citation or equation reference failures, "
        "and how captions, labels, units, legends and table headings communicate a result. Cite a specific instance "
        "and its consequence. Make visual claims about legibility, clipping, color or layout only from a supplied "
        "visual observation on that exact page. PDF extraction artifacts and isolated typos do not establish a defect "
        "in the LaTeX source or invalidate an otherwise strong scientific contribution."
    ),
    INNOVATION: (
        "What does this work enable a researcher or practitioner to do or understand differently? "
        "Compare the specific contribution with named, verified prior work when available, and explain how "
        "the evidence supports practical significance, a reusable insight, or an unusual and productive viewpoint. "
        "A new question, diagnostic or negative result using familiar methods can merit a strong recommendation. "
        "Distinguish demonstrated value from speculative impact. If comparisons are thin, qualify field-level novelty "
        "and still evaluate the paper's evidenced contribution. Avoid unsupported first-in-field claims."
    ),
}
REVIEWER_ROLES = tuple(BRIEFS)

# Retrieval queries describe manuscript language, whereas the briefs above instruct the reviewer.
QUERIES = {
    THEORY: "formal definition, modeling assumptions, mechanism, objective function, interpretation, necessary conditions, identifiability, derivation, guarantee",
    EXPERIMENTS: "evaluation protocol, comparison baseline, control, data split, ablation, sensitivity, confidence interval, generalization, experimental results table",
    CLARITY: "implementation details, algorithm steps, pseudo-code, system prompt, configuration, hyperparameters, training recipe, random seeds, preprocessing, code release, instructions for replication",
    PRESENTATION: "academic writing clarity, notation, captions, figure axes, units and legends, table headings, cross-references and typography",
    INNOVATION: "research contribution, practical significance, distinctive insight, prior work, transferable design principle, reusable diagnostic, surprising observation",
}


def reviewer_prompt(role):
    return f"You are the {role} reviewer. {BRIEFS[role]} "


def reviewer_passages(paper, limit=5):
    """Rank locatable source passages independently for each reading of the same PDF."""
    pages = paper["pages"]
    # Some PDFs flatten a bibliography and an appendix into the same text stream.
    # Keep appendix evidence, but avoid retrieving a citation list as a result of this paper.
    from .prior_work import bibliography
    refs = bibliography(paper)
    if not refs:
        match = re.search(r"\b(?:REFERENCES|BIBLIOGRAPHY)\b(.*?)(?=\bAPPENDIX\b|(?:^|\s)A\s+[A-Z][A-Z ]{6,}|\Z)",
                          "\n".join(pages), re.S)
        refs = match[1] if match else ""
    candidates = {}
    for section in paper.get("sections", []):
        quote = section["excerpt"]
        page = section["start_page"]
        if quote and quote not in refs and quote in pages[page-1]:
            candidates[page, quote] = section["heading"] + " " + quote
    for row in passages(paper):
        if row["quote"] not in refs:
            candidates.setdefault((row["page"], row["quote"]), row["quote"])
    selected = {role: [] for role in REVIEWER_ROLES}
    if not candidates:
        return selected
    entries = list(candidates)
    vectors = embed([*QUERIES.values(), *candidates.values()])
    n = len(REVIEWER_ROLES)
    similarities = vectors[n:] @ vectors[:n].T
    for role_index, role in enumerate(REVIEWER_ROLES):
        # Favor evidence that distinguishes the lens, while letting a shared passage serve two questions.
        ranks = similarities[:, role_index] - 0.5 * similarities.mean(axis=1)
        per_page = {}
        for index in (-ranks).argsort(kind="stable"):
            page, quote = entries[index]
            chosen = selected[role]
            if per_page.get(page, 0) >= 2 or any(quote in r["quote"] or r["quote"] in quote for r in chosen):
                continue
            chosen.append(dict(id=f"excerpt-{index+1}", page=page, quote=quote))
            per_page[page] = per_page.get(page, 0) + 1
            if len(chosen) == limit:
                break
    return selected


def reviewer_conflicts(role, conflicts):
    # The consistency checker currently checks table arithmetic, cohort scope and implementation protocols.
    # The full set also appears in the manuscript-level evidence view.
    owners = {"results": EXPERIMENTS, "scope_check": EXPERIMENTS, "protocol": CLARITY}
    return [row for row in conflicts if owners.get(row["kind"], THEORY) == role]


async def specialist_finding(role, sources, ask, evidence_mode=""):
    """Ask a narrow question before the model weighs the whole paper."""
    from .model import ModelJSONError
    if not sources:
        return None
    prompt = reviewer_prompt(role) + (
        "Choose ONE source below and answer your specialist question in a single sentence. "
        "Name the actual variable, phrase, control, comparison or labeled element and explain its specific consequence. "
        "For a caption or extracted table label, assess only what its wording communicates. "
        "Use a visual observation for any judgment about the appearance of a rendered figure or table. "
        "For a literature comparison, name the compared approach when supplied. "
        "If no observation is supported, return ref 0 and an empty assessment. "
        'Return {"ref":1,"assessment":"..."} using the integer ref beside the chosen source.'
    )
    options = [dict(ref=i, **row) for i, row in enumerate(sources, 1)]
    try:
        answer = await ask(prompt, evidence_mode=evidence_mode, sources=options)
    except ModelJSONError:
        return None
    ref, finding = answer.get("ref"), answer.get("assessment")
    if isinstance(ref,str) and ref.isdecimal():
        ref = int(ref)
    if type(ref) is not int or not 1 <= ref <= len(sources) or not isinstance(finding,str) or not finding.strip():
        return None
    source = sources[ref-1]
    try:
        checked = await ask(
            reviewer_prompt(role) +
            "Independently read this one source. Report only what can be inferred here. For a table, "
            "use the two methods and metric named on ONE row; a different row describes a different experiment. "
            "Keep a percentage with its named dataset. For a pointer to an appendix, describe where to look. "
            "If working from a caption, describe what information its words convey; the graphic itself is unobserved. "
            "Return one exact short quote (anchor) plus a single sentence (assessment) naming the detail and "
            "its consequence. If the source cannot support a specialist judgment, leave both empty. "
            'Use exactly {"anchor":"verbatim words from source.quote","assessment":"one sentence"}.',
            source=source, evidence_mode=evidence_mode)
    except ModelJSONError:
        return None
    anchor = checked.get("anchor") or checked.get("quote")
    if not anchor and isinstance(checked.get("source"),dict):
        anchor = checked["source"].get("quote")
    assessment = checked.get("assessment")
    if not isinstance(anchor,str) or not anchor.strip() or anchor.strip() not in source["quote"]:
        return None
    if not isinstance(assessment,str) or not assessment.strip():
        return None
    return dict(assessment=assessment.strip(), source=dict(source,quote=anchor.strip()))
