"""Retrieve historical examples for context, without importing their numeric ratings."""
import re
import sqlite3
from collections import Counter
from functools import lru_cache

from .kb import DATA
from .paper import is_manuscript_title

POOL = DATA / 'comparison-pool.sqlite'
STOP = set('about above across after against among approach based between compared demonstrate experiments first from have improve including learning method model models most on our paper performance proposed results show than that their these this using with which'.split())


@lru_cache(maxsize=1)
def comparison_counts(version):
    with sqlite3.connect(f'{POOL.as_uri()}?mode=ro',uri=True) as db:
        return [dict(venue=v,papers=p,reviews=r) for v,p,r in db.execute(
            "SELECT venue,count(DISTINCT papers.paper_id),count(reviews.id) FROM papers JOIN reviews USING(paper_id) GROUP BY venue ORDER BY venue")]


def comparison_reviews(claims, first_page, before, limit=5, abstracts=False):
    tokens = re.findall(r'[a-z][a-z0-9-]{3,}', ' '.join(c['text'] for c in claims).lower())
    terms = Counter(t for t in tokens if t not in STOP).most_common(28)
    if not terms or not POOL.exists():
        return []
    expression = ' OR '.join(f'"{term}"' for term,_ in terms)
    with sqlite3.connect(f'{POOL.as_uri()}?mode=ro',uri=True) as db:
        cutoff_operator = "<" if abstracts else "<="
        matches = db.execute(f"""
            SELECT paper_id,title,venue,abstract FROM papers WHERE papers MATCH ?
            AND EXISTS (SELECT 1 FROM reviews WHERE reviews.paper_id=papers.paper_id AND posted{cutoff_operator}?)
            ORDER BY bm25(papers,4,1) LIMIT ?
        """,(expression,before,limit+10))
        examples=[]
        for pid,title,venue,abstract in matches:
            if is_manuscript_title(title,first_page):
                continue
            if abstracts:
                if not abstract:
                    continue
                date_bound=db.execute('SELECT min(posted) FROM reviews WHERE paper_id=?',(pid,)).fetchone()[0]
                examples.append(dict(title=title,abstract=abstract,published=date_bound,
                                     url=f'https://openreview.net/forum?id={pid}'))
                if len(examples)==limit:
                    break
                continue
            reviews=db.execute('SELECT id,excerpt FROM reviews WHERE paper_id=? AND posted<=? ORDER BY id',(pid,before))
            rid,excerpt=max(reviews,key=lambda row:sum(weight for word,weight in terms if word in row[1][:700].lower().split()))
            examples.append(dict(title=title,venue=venue,review_excerpt=excerpt[:700],
                                 source=f'https://openreview.net/forum?id={pid}&noteId={rid}'))
            if len(examples)==limit:
                break
        return examples
