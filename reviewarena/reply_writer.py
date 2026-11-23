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


async def compose_response(ask, paper, critique, evidence, step, history):
    prompt = ("Write a concise English rebuttal paragraph addressed to the reviewer, in the authors' voice. "
              "Answer this specific reviewer point in the first sentence. Use the title or opening for topic only. "
              "Base factual claims solely on the selected manuscript evidence and respect what it actually addresses. "
              "If evidence is absent or partial, acknowledge what remains unanswered. Express the suggested next step "
              "as future work and commit ONLY to that step. No new studies, sites or changes. Use the historical authors' replies for tone, directness and organization only. "
              "Use original wording; do not import their methods, results, names, commitments or numbers. "
              "Return JSON with response (one paragraph, no headings or planning notes).")
    inputs = dict(manuscript_title_or_opening=paper.get('title') or paper['pages'][0][:550],
                  reviewer_point=critique, existing_evidence=evidence, suggested_next_step=step,
                  historical_style_examples=style_examples(history))
    if evidence is None:
        prompt += (" No passage is selected. Give a direct first-person response in two sentences: "
                   "acknowledge the unanswered point and state specifically what we will do. "
                   "Do not describe the paper, any current analysis or its results.")
    for attempt in range(2):
        result = await ask(prompt, **inputs)
        draft = result.get('response')
        if not isinstance(draft, str) or not draft.strip():
            continue
        # A stylistic exemplar must never become the evidence for a completed experiment.
        check = await ask("Identify any unsupported factual claim or added commitment in the draft. "
                          "Compare what the authors propose to do to the allowed next step: a different "
                          "experiment, new dataset or extra site is an unsupported commitment. "
                          "With no manuscript evidence, an acknowledgment and a promise to perform exactly "
                          "the allowed next step are fully supported. Judge fidelity rather than whether "
                          "the reviewer has received a complete experimental answer. "
                          "Return JSON with unsupported_quote (an exact substring of the draft, or empty string).",
                          draft=draft, current_evidence=evidence, allowed_next_step=step)
        problem=check.get('unsupported_quote')
        if isinstance(problem,str) and not problem.strip():
            return draft.strip()
        # A future-tense paraphrase that exactly preserves the planned action needs no
        # factual inference. Keep that sentence and discard any additional commitments.
        if not evidence and draft.strip().casefold().startswith('we will '):
            action=draft.strip()[8:]
            def content_words(text):
                return [m for m in re.finditer(r"[\w'-]+",text) if m[0].casefold() not in ('a','an','the')]
            proposed=content_words(step)
            generated=content_words(action)[:len(proposed)]
            if proposed and [w[0].casefold() for w in generated]==[w[0].casefold() for w in proposed]:
                return 'We will '+action[:generated[-1].end()]+'.'
        inputs.pop('historical_style_examples',None)
        prompt=("Write a natural, concise direct answer to reviewer_point in the authors' voice. "
                "Sentence one answers using existing_evidence, or acknowledges the missing evidence. "
                "Sentence two restates suggested_next_step using 'we will'. Do not add any other plan, "
                "measurement, figure, dataset or rationale. Return JSON with response as a string.")
        inputs['correction'] = str(problem or 'Remove unverified factual claims and new commitments.')[:450]
    # Preserve the other reviewer points if the model cannot produce a grounded paraphrase.
    opener = (f"On page {evidence['page']}, we state: “{evidence['quote']}”"
              if evidence else "We appreciate the question and will address it in the revision.")
    return f"{opener} Our next step is to {step[:1].lower()}{step[1:].rstrip('.')}."
