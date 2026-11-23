"""Check whether a close-call rating is consistent with page-grounded manuscript evidence."""
import re

from .model import ModelJSONError


async def check_rating(report, role, claims, conflicts, pages, score_labels, ask):
    evidence = []
    for finding in conflicts + report.get('weaknesses', []):
        if finding.get('kind') == 'scope_check':
            continue
        quotes = []
        for item in finding.get('evidence', []):
            page, quote = item.get('page'), item.get('quote')
            if isinstance(page, int) and 1 <= page <= len(pages) and isinstance(quote,str) and quote.strip():
                if quote in pages[page-1]:
                    quotes.append(dict(page=page, quote=quote))
        kind = finding.get('kind')
        if kind == 'protocol':
            if len({q['quote'] for q in quotes}) < 2:
                continue
            # Explicit alternative configurations need separate within-configuration evidence.
            if any(re.search(r'\b(baseline|ablation|variant|control model)\b',q['quote'],re.I) for q in quotes):
                contexts=[set(re.findall(r'\b(?:baseline|ablation|variant|control model)\b',q['quote'].lower())) for q in quotes]
                if any(c!=contexts[0] for c in contexts[1:]):
                    continue
        if quotes:
            evidence.append(dict(ref=len(evidence)+1,kind=kind,issue=finding['issue'],passages=quotes))
    if not evidence or report['score'] == min(score_labels):
        return
    # Provide surrounding text to distinguish conflicting instructions from separate variants.
    for entry in evidence:
        for passage in entry['passages']:
            page = pages[passage['page']-1]
            start = page.index(passage['quote'])
            passage['context'] = page[max(0,start-250):start+len(passage['quote'])+250]
    try:
        verdict = await ask(
            "Review your provisional rating against the primary evidence. Which specific defect, if any, "
            "would require a substantive correction before the paper's central result can be trusted or "
            "reproduced? Check the actual quoted passages for different variants, cohorts or stages and "
            "weigh remaining strengths. Typos, awkward writing, optional tests, and small secondary "
            "discrepancies alone warrant no downgrade. Two mutually exclusive accounts of the procedure "
            "used for the central result are a major defect when the paper does not identify which produced it. "
            "Choose severity: major (a central method or result requires substantive repair), fundamental "
            "(the central claim is untenable and no independent support remains), or limited (including "
            "uncertain, resolved, and presentation-only issues). Return JSON with severity, ref (integer "
            "identifying the decisive evidence, 0 for limited), and rationale (one or two sentences naming "
            "the conflicting facts or invalid inference, and the concrete impact on the claimed result).",
            role=role, claims=claims, observations=evidence, strengths=report.get('strengths',[]))
    except ModelJSONError:
        return
    ref, reason = verdict.get('ref'), verdict.get('rationale')
    level = verdict.get('severity')
    if level not in ('major','fundamental') or type(ref) is not int or not 1 <= ref <= len(evidence):
        return
    if not isinstance(reason,str) or not reason.strip():
        return
    selected = evidence[ref-1]['passages']
    if evidence[ref-1]['kind']=='protocol':
        try:
            scope=await ask(
                "Find a textual resolution for the apparent conflict: does the manuscript explicitly "
                "assign the two instructions to different variants or stages? Return one flat JSON "
                "object with exactly two keys: resolved (boolean) and resolution_quote (exact clause "
                "identifying the separate configuration, or empty string if none).",
                first=selected[0]['context'], second=selected[1]['context'])
        except ModelJSONError:
            return
        resolution=scope.get('resolution_quote')
        if scope.get('resolved') is not False:
            if scope.get('resolved') is not True or not isinstance(resolution,str):
                return
            if len(resolution.split())>=3 and any(resolution in p['context'] for p in selected):
                return
        # Ambiguity in the recipe does not alone establish that the measured outcome is false.
        level='major'
    if level=='fundamental':
        try:
            confirmation=await ask(
                "Can the claimed outcome still be true despite the quoted problem? "
                "An ambiguous procedure can make an outcome unrepeatable even if that outcome is true. "
                "Return JSON with directly_invalidated (boolean) and explanation. Set true only if the "
                "evidence establishes that a necessary premise fails or the central evaluation cannot "
                "test the claim at all, and no independent result supports it. If the issue only makes "
                "the method ambiguous, or concerns another metric, set false.",
                claims=claims,passages=selected,strengths=report.get('strengths',[]))
        except ModelJSONError:
            confirmation={}
        if confirmation.get('directly_invalidated') is not True:
            level='major'
    label = 'Reject' if level == 'major' else 'Strong reject'
    ceiling = next(n for n,name in score_labels.items() if name == label)
    if report['score'] <= ceiling:
        return
    page_numbers = ', '.join(str(n) for n in sorted({p['page'] for p in selected}))
    report['rating_check'] = dict(initial_score=report['score'],severity=level,
                                  evidence=[dict(page=p['page'],quote=p['quote']) for p in selected])
    report['score'] = ceiling
    report['summary'] = f"{reason.strip()} (p. {page_numbers})"
