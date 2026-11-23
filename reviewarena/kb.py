import os,json
from pathlib import Path
from functools import lru_cache
import duckdb,numpy as np,pyarrow.parquet as pq
from .embedding import embed
from .review_vectors import passage_vectors
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'

def current_snapshot():
    configured=os.getenv('REVIEWARENA_KB_SNAPSHOT')
    if configured:return Path(configured)
    pointer=DATA/'active-index.json'
    return DATA/'index-snapshots'/json.loads(pointer.read_text()) if pointer.exists() else DATA

def labeled_data(name,snapshot=None):
    return (snapshot or current_snapshot()) / name

@lru_cache(maxsize=3)
def index(field,path,version):
    rows=pq.read_table(path).to_pylist()
    return rows,passage_vectors(rows,field)

@lru_cache(maxsize=1)
def prior_table(path,version):
    return pq.read_table(path).to_pylist()

@lru_cache(maxsize=1)
def claim_prototypes(names):
    return names,embed(list(names))

@lru_cache(maxsize=4)
def family_ratings(snapshot):
    path=snapshot/'family-audits.json'
    return {tuple(r['key']):r for r in json.loads(path.read_bytes())} if path.exists() else {}


def search(query,k=20,field='trigger_text',claim_type='',paper_type='',require_reply=False):
    snapshot=current_snapshot()
    critiques=snapshot/'critique.parquet'
    taxonomy=snapshot/'taxonomy.parquet'
    rows,m=index(field,critiques,critiques.stat().st_mtime_ns)
    audit=family_ratings(snapshot)
    sim=m@embed(["Represent this sentence for searching relevant passages: "+query])[0]
    families={}
    assignments={}
    prior={}
    pool_review_ids=set()
    nearest=''
    closest=''
    if field=='trigger_text':
        corpus=prior_table(taxonomy,taxonomy.stat().st_mtime_ns) if taxonomy.exists() else rows
        families={r['category']:r.get('family',r['category']) for r in corpus}
        assignments={r['category']:r.get('family_assignment') for r in corpus}
    if field=='trigger_text' and claim_type:
        types,prototypes=claim_prototypes(tuple(sorted({r['claim_type'] for r in corpus if r['claim_type']})))
        nearest=types[int(np.argmax(prototypes@embed([claim_type])[0]))]
        pool=[r for r in corpus if r['claim_type']==nearest]
        if paper_type and pool:
            options=tuple(sorted({r['paper_type'] for r in pool if r.get('paper_type')}))
            if options:
                names,paper_vectors=claim_prototypes(options)
                closest=names[int(np.argmax(paper_vectors@embed([paper_type])[0]))]
                joint=[r for r in pool if r['paper_type']==closest]
                if joint:pool=joint
        family_reviews={}
        for row in pool:
            group=row.get('family',row['category'])
            family_reviews.setdefault(group,set()).add(row['review_id'])
        pool_review_ids={row['review_id'] for row in pool}
        prior={group:len(ids)/len(pool_review_ids) for group,ids in family_reviews.items()}
    score=[float(s) if field!='trigger_text' else .75*float(s)+.15*prior.get(families.get(r['category'],r['category']),0)+.1*r['severity']/3 for r,s in zip(rows,sim)]
    seen=set();out=[]
    for j in np.argsort(score)[::-1]:
        r=rows[j]; key=r['paper_id'] if field=='abstract' else families.get(r['category'],r['category'])
        if require_reply and not (r.get('reply_id') and r.get('reply')):continue
        judged=audit.get((r['paper_id'],r['review_id'],r['category'],r['critique_text'],r['trigger_text']))
        if field=='trigger_text' and judged and judged['verdict']!='fits':continue
        if key in seen or sim[j]<=0:continue
        seen.add(key)
        result={**r,'score':round(score[j],4)}
        if judged:result.update(family_fit=judged['verdict'],family_fit_reason=judged['reason'])
        if field=='trigger_text':
            frequency=prior.get(key,0)
            result.update(family=key,family_assignment=assignments.get(r['category']),similarity=float(sim[j]),conditional_frequency=frequency,
                          prior_reviews=round(frequency*len(pool_review_ids)),prior_total=len(pool_review_ids),
                          matched_claim_type=nearest,matched_paper_type=closest)
        out.append(result)
        if len(out)>=k:break
    return out

def historical_review_section(paper_id, review_id, quote):
    """Find the archived review field containing the displayed quotation."""
    needle = ' '.join(quote.split())
    if not needle:
        return None
    with duckdb.connect(str(DATA/'history.duckdb'), read_only=True) as db:
        row = db.execute('select content from reviews where paper_id=? and id=?',
                         [paper_id, review_id]).fetchone()
    if row:
        for field, value in json.loads(row[0]).items():
            if isinstance(value, dict):
                value = value.get('value')
            if isinstance(value, str) and needle in ' '.join(value.split()):
                return field, value
    return None


def stats():
    with duckdb.connect(str(DATA/'history.duckdb'),read_only=True) as db:
        return db.sql("select p.year,count(distinct p.id) papers,count(r.id) official_reviews from papers p left join reviews r on p.id=r.paper_id group by p.year order by p.year").df().to_dict('records')

def accepted_decision(decision):
    text=(decision or '').lower()
    if 'reject' in text:return False
    if any(word in text for word in ('accept','poster','oral','spotlight','notable')):return True
    return None

def outcomes(categories,severities=None,snapshot=None):
    if not categories:return {'accepted':0,'papers':0,'rate':None,'matched_papers':0}
    table=labeled_data('taxonomy.parquet',snapshot)
    with duckdb.connect() as db:
        if table.exists():
            if severities:
                rows=db.execute("with t as (select * from read_parquet(?)), q as (select unnest(?) category,unnest(?) severity), cohort as (select distinct t.family,q.severity from t join q on q.category=t.category) select distinct t.paper_id,lower(t.decision) from t join cohort c on t.family=c.family and t.severity=c.severity",[str(table),categories,severities]).fetchall()
            else:
                rows=db.execute("with t as (select * from read_parquet(?)) select distinct paper_id,lower(decision) from t where family in (select family from t where category in (select unnest(?)))",[str(table),categories]).fetchall()
        elif severities:
            rows=db.execute("""
                with requested as (select unnest(?) as category, unnest(?) as severity)
                select distinct c.paper_id, lower(c.decision)
                from read_parquet(?) c join requested using(category, severity)
            """,[categories,severities,str(labeled_data('critique.parquet',snapshot))]).fetchall()
        else:
            rows=db.execute("select distinct paper_id,lower(decision) from read_parquet(?) where category in (select unnest(?))",[str(labeled_data('critique.parquet',snapshot)),categories]).fetchall()
    labels=[label for _,d in rows if (label:=accepted_decision(d)) is not None]
    return {'accepted':sum(labels),'papers':len(labels),'rate':sum(labels)/len(labels) if labels else None,'matched_papers':len(rows)}

@lru_cache(maxsize=1)
def abstract_vectors(version):
    with np.load(DATA/'paper_vectors.npz') as index:
        return index['ids'],index['vectors']

def similar_papers(query,k=5):
    import json
    path=DATA/'paper_vectors.npz'
    ids,vec=abstract_vectors(path.stat().st_mtime_ns)
    scores=vec@embed(["Represent this sentence for searching relevant passages: "+query])[0]
    out=[]
    with duckdb.connect(str(DATA/'history.duckdb'),read_only=True) as db:
        for j in np.argsort(-scores):
            pid=str(ids[j])
            notes=db.execute('select id,content from reviews where paper_id=? order by id',[pid]).fetchall()
            if not notes:continue
            title,abstract=db.execute('select title,abstract from papers where id=?',[pid]).fetchone()
            reviews=[]
            for rid,content in notes:
                fields=json.loads(content)
                passages=[str(v) for key,v in fields.items() if any(x in key.lower() for x in ('weak','review','limitation','question'))]
                if passages:reviews.append({'review_id':rid,'text':' '.join(passages)[:1600]})
            out.append(dict(paper_id=pid,title=title,abstract=abstract,reviews=reviews,source='https://openreview.net/forum?id='+pid))
            if len(out)>=k:break
    return out
