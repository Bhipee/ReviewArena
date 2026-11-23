"""Trace an adapted question back to the historical check it most closely resembles."""
import numpy as np

from .embedding import embed


def source_ranks(candidates):
    selected=[i for i,c in enumerate(candidates) if c.get('target_question')]
    if not selected or len(candidates)<2:
        return {}
    checks=[c.get('transfer_question') or c['critique_text'] for c in candidates]
    proposals=[candidates[i]['target_question'] for i in selected]
    vectors=embed(checks+proposals)
    similarities=vectors[len(checks):]@vectors[:len(checks)].T
    results={}
    for i,scores in zip(selected,similarities):
        highest=int(np.argmax(scores))
        results[i]=dict(rank=1+int(np.sum(scores>scores[i]+1e-6)),compared=len(checks),
                        historical_question=checks[i],closest_category=candidates[highest]['category'],source_similarity=float(scores[i]))
    return results
