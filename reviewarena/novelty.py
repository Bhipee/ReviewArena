"""Compare page-grounded contributions to the content of dated research abstracts."""
import re
from .comparisons import comparison_reviews
from .model import ModelJSONError
from .paper import is_manuscript_title


async def compare_contributions(paper, claims, publications, before, ask):
    pages = paper['pages']
    results = []
    for claim in claims:
        page = claim.get('page')
        text = claim.get('text', '')
        if not isinstance(page, int) or not 1 <= page <= len(pages) or not text or text not in pages[page-1]:
            continue
        row = dict(claim=text, page=page, status='Insufficient evidence')
        results.append(row)
        local = comparison_reviews([claim], pages[0], before, limit=4, abstracts=True)
        candidates = []
        seen = set()
        for source in publications + local:
            title = source['title'].strip()
            key = title.casefold()
            if (not title or key in seen or not source.get('abstract') or not source.get('url')
                    or not source.get('published') or source['published'] >= before
                    or is_manuscript_title(title, pages[0])):
                continue
            seen.add(key)
            candidates.append(source)
        if not candidates:
            continue
        evidence = [p for p in paper.get('sections', [])
                    if re.search(r'result|experiment|evaluat|theor|ablation', p['heading'], re.I)]
        try:
            response = await ask(
                "Compare the manuscript contribution with the single closest relevant abstract. "
                "Return ref (one-based source number, or 0 if unrelated), prior_quote (copy a full "
                "specific clause verbatim from that abstract). Choose a source discussing the actual "
                "contribution or a relevant part of the method. A topic keyword alone is insufficient.",
                contribution=text, abstracts=[dict(ref=i, title=s['title'], abstract=s['abstract'][:3000])
                                             for i,s in enumerate(candidates,1)])
        except ModelJSONError:
            continue
        idx = response.get('ref')
        if type(idx) is not int or not 1 <= idx <= len(candidates):
            continue
        source = candidates[idx-1]
        quote = response.get('prior_quote')
        if not isinstance(quote,str) or len(quote.split()) < 5 or quote not in source['abstract'][:3000]:
            continue
        # A matching quote establishes provenance. Independently check that its meaning supports the inference.
        try:
            check = await ask("Read these two quotations alone. Identify what each method actually does. "
                              "Classify the relation as overlapping if both describe the same specific "
                              "contribution, shared_component for a shared ingredient, distinct only for an "
                              "explicit technical difference, or unclear. Never infer a difference from silence. "
                              "Return JSON with relation and comparison (one sentence stating the common "
                              "operation or both sides of the difference).",
                              manuscript=text, prior=quote)
        except ModelJSONError:
            continue
        relation=check.get('relation')
        comparison=check.get('comparison')
        if relation not in ('distinct','overlapping','shared_component') or not isinstance(comparison,str) or not comparison.strip():
            continue
        row.update(status=relation, title=source['title'], url=source['url'], prior_quote=quote,
                   comparison=comparison.strip())
        if relation!='distinct' or not evidence:
            continue
        try:
            support=await ask("Does an experiment, ablation or theoretical result directly validate "
                              "this particular difference? Copy one exact clause from the manuscript "
                              "passages as validation_quote, or return an empty string for indirect evidence.",
                              difference=comparison, manuscripts=[p['excerpt'][:1100] for p in evidence[:6]])
        except ModelJSONError:
            continue
        validation=support.get('validation_quote')
        if isinstance(validation,str) and len(validation.split())>=5 and any(validation in p['excerpt'][:1100] for p in evidence[:6]):
            for n, content in enumerate(pages,1):
                if validation in content:
                    row.update(validation=validation, validation_page=n)
                    break
    return results
