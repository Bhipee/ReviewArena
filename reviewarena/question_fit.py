"""Check if the answer requested by an adapted question addresses the historical reviewer's point."""


async def check_question_fit(item, ask):
    result=await ask(
        'Compare the evidence needed to answer two scientific questions. First summarize the test or '
        'objection in the original reviewer quotation. Then summarize what a complete answer to the new '
        'question would establish. Decide whether these are the same concrete scientific check after '
        'substituting the target manuscript entities. Sharing terminology or both requesting justification '
        'is insufficient. Judge separately whether the new question assumes a setting or result absent '
        'from the target claim. Return JSON with original_test, new_test, same_check (boolean), '
        'grounded_in_claim (boolean), and reason (one sentence).',
        original_reviewer=item['source_quote'], historical_question=item['source_check'],
        manuscript_claim=item['target_claim'], new_question=item['target_question'])
    return dict(same_check=result.get('same_check') if type(result.get('same_check')) is bool else None,
                grounded_in_claim=result.get('grounded_in_claim') if type(result.get('grounded_in_claim')) is bool else None,
                original_test=result.get('original_test',''),new_test=result.get('new_test',''),reason=result.get('reason',''))
