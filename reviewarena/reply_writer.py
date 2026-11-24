"""Compose a reviewer-facing reply using retrieved replies exclusively as style examples."""
import json
import re


def style_examples(history):
    examples = []
    for item in history:
        raw = item.get('reply')
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                pass
        if isinstance(raw, dict):
            fields = {k.casefold(): v for k, v in raw.items()}
            raw = fields.get('comment') or fields.get('response')
        if isinstance(raw, dict):
            raw = raw.get('value')
        if isinstance(raw, str) and raw.strip() and raw.strip()[:1200] not in examples:
            examples.append(raw.strip()[:1200])
        if len(examples) == 3:
            break
    return examples


PLANNING_LANGUAGE = re.compile(
    r"\b(?:we(?:\s+will|'ll|\s+(?:plan|intend|aim)\s+to)|in (?:a|the) (?:future|next|upcoming) revision|"
    r"future work|our next step|we (?:agree|appreciate|acknowledge)|(?:we )?have (?:clarified|added|revised)|thank (?:you|the reviewer))\b", re.I)
SLOT = re.compile(r"\[([^\[\]\n]{2,160})\]")


async def compose_response(ask, paper, critique, evidence, step, history, *, action):
    instructions = {
        'discussion': "Offer a reasoned perspective on the specific question. Explain a plausible mechanism, "
                      "trade-off or boundary condition. Mark untested ideas as hypotheses. A conditional "
                      "argument can stand on its own. Do not assign a revision, propose an experiment as a task, "
                      "or imply that the manuscript has tested the idea.",
        'clarify': "Give the specific answer using manuscript evidence, then explain why it resolves the concern.",
        'revise': "Write the clarified definition, reasoning or limitation itself. If a fact needed to answer "
                  "is unavailable, put a specific fill-in field for that fact in square brackets.",
        'experiment': "Write the answer in the form of a result the authors can finalize. Name the quantity or "
                      "comparison the reviewer is asking about. Leave unknown measurements in descriptive "
                      "square-bracket fields. If the direction or interpretation is unknown, leave it open. "
                      "Compose grammatical sentences with descriptive placeholders directly in them."
    }
    prompt = ("Write the paragraph the authors would send to this reviewer after filling any missing facts. "
              "Start with the technical substance. Use direct English and address the underlying scientific "
              "question. Omit salutation, agreement, thanks, question recap and promises about revisions. "
              "The suggested action is private planning context. Historical replies illustrate style only. "
              "Use one or two sentences. Do not announce that you have clarified anything. Keep all unverified facts, numbers and results in fill-in fields; do not assert that new work "
              "or edits have already been completed. Return JSON with response, one short paragraph. "
              + instructions[action])
    inputs = dict(topic=paper.get('title') or paper['pages'][0][:550], reviewer_point=critique,
                  manuscript_evidence=evidence, authors_private_plan=step, style_examples=style_examples(history))
    examples=inputs.pop('style_examples')
    if examples:
        style=await ask("Read these author replies for style. Return JSON with style (one short English phrase "
                        "describing how they structure a substantive answer). No topics, facts, quotations, "
                        "numbers, greetings, agreement or suggestions for future work.",historical_replies=examples)
        if isinstance(style.get('style'),str):
            inputs['style']=style['style'][:220]
    for _ in range(2):
        result = await ask(prompt, **inputs)
        draft = result.get('response')
        if not isinstance(draft, str) or not draft.strip():
            continue
        slots = SLOT.findall(draft)
        if re.match(r"(?:the (?:review|reviewer|manuscript) (?:suggests|asks|states)|to address (?:the|this) (?:concern|question))", draft.strip(), re.I):
            inputs['correction'] = 'Remove the recap. Give the definition, measurement, or explanation directly.'
            continue
        if PLANNING_LANGUAGE.search(draft.replace('’', "'")):
            inputs['correction'] = 'Remove courtesy and future-work language. Start with the direct answer.'
            continue
        needs_slot = action == 'experiment' or (action == 'revise' and not evidence)
        if needs_slot and not any(any(c.isalpha() for c in slot) for slot in slots):
            inputs['correction'] = 'Insert a descriptive square-bracket field where the missing result or author clarification belongs.'
            continue
        discussion_check = (" A clearly conditional scientific argument is allowed. Flag unsupported assertions "
                            "about what the authors measured, found or changed." if action=='discussion' else "")
        check = await ask("Check only factual grounding of the author reply. Treat bracketed fields as "
                          "unknowns. Does the text outside the fields invent a finding, outcome direction, "
                          "measurement, or completed change? Ignore harmless restatements of the question. "
                          "Return JSON with unsupported_quote (the exact unsupported text, or empty string)."+discussion_check,
                          draft=draft, reviewer_point=critique, manuscript_evidence=evidence)
        if check.get('unsupported_quote') == '':
            return draft.strip()
        inputs['correction'] = 'Replace unsupported text with a specific bracketed field: '+str(check.get('unsupported_quote',''))
    if action=='experiment':
        # Small models sometimes omit literal brackets. Let them name the observations;
        # the renderer supplies the editable result fields.
        result=await ask(
            "Identify each scientific quantity needed for a direct answer. Return a JSON object with "
            "primary (noun phrase naming the observation, including its population) and comparison "
            "(noun phrase naming the relationship, overlap or contrast also requested; empty if none). "
            "Include the entities being compared. Supply no values, conclusions or prose.",
            reviewer_point=critique, experiment=step)
        primary, comparison=result.get('primary'),result.get('comparison')
        def quantity(value):
            return isinstance(value,str) and 1<=len(value.split())<=20 and not re.search(r'[\[\]{}\n]',value)
        if quantity(primary):
            sentences=[f"For {primary.strip(' .:')}, we observe [value or pattern]."]
            if quantity(comparison) and comparison.casefold()!=primary.casefold():
                sentences.append(f"The comparison shows [measured {comparison.strip(' .:')}].")
            return ' '.join(sentences)
    # Leave outstanding facts visibly unfilled even if the model fails both checks.
    if action == 'discussion':
        return f"[Give the authors’ interpretation of this point and the assumptions it depends on: {critique}]"
    if action == 'experiment':
        return f"[Report the measurements for this comparison: {step.rstrip('.')}.] [State what those measurements establish about the reviewer’s question.]"
    if evidence and evidence.get('role') == 'addresses':
        return f"“{evidence['quote']}” (p. {evidence['page']})."
    return f"[Supply the specific clarification: {step.rstrip('.')}.]"
