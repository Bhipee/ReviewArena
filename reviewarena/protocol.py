"""Identify the actual model, source code and indexes used by a review."""
import hashlib,os
from urllib.parse import urlsplit
from functools import lru_cache
from .kb import ROOT,DATA,labeled_data
@lru_cache(maxsize=128)
def digest(path,size,mtime):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1<<20),b''):h.update(block)
    return h.hexdigest()
def protocol(method,venue,snapshot=None):
    paths=[ROOT/'reviewarena'/f for f in ('model.py','paper.py','sections.py','settings.py','claims.py','lab_reviewer.py','embedding.py','reviewer_roles.py','workflow.py','tools.py')]
    paths += [ROOT/'skills'/name/'SKILL.md' for name in (venue.lower()+'-reviewer','area-chair')]
    if method!='A':paths+=[ROOT/'reviewarena/kb.py',ROOT/'reviewarena/embedding.py',ROOT/'reviewarena/review_vectors.py',ROOT/'mcp_reviewkb_server.py',DATA/'bge-small/model_optimized.onnx']
    if method=='B':paths+=[DATA/'paper_vectors.npz']
    if method in 'CD':paths+=[ROOT/'reviewarena/transfer.py',labeled_data('critique.parquet',snapshot),labeled_data('taxonomy.parquet',snapshot),labeled_data('family-audits.json',snapshot)]
    if method=='D':paths+=[ROOT/'reviewarena/named_works.py',ROOT/'reviewarena/verifier.py',ROOT/'mcp_scholar_server.py',ROOT/'skills/critique-verifier/SKILL.md']
    if method=='D':paths+=[ROOT/'reviewarena/comparisons.py',ROOT/'reviewarena/novelty.py',ROOT/'reviewarena/prior_work.py',ROOT/'reviewarena/investigation.py',ROOT/'reviewarena/severity.py',ROOT/'reviewarena/presentation_review.py',ROOT/'reviewarena/consistency.py',DATA/'comparison-pool.sqlite']
    if method=='D':paths.extend(sorted((DATA/'publication-records').glob('*.json')))
    api=os.getenv('REVIEWARENA_API_URL','http://127.0.0.1:8766/v1')
    model=os.getenv('REVIEWARENA_MODEL','default_model')
    endpoint=urlsplit(api)
    local_models={8766:('model','Qwen2.5-3B-Instruct-4bit'),8767:('model-7b','Qwen2.5-7B-Instruct-4bit')}
    if endpoint.hostname in ('127.0.0.1','localhost') and model=='default_model' and endpoint.port in local_models:
        directory,model=local_models[endpoint.port]
        paths.append(DATA/directory/'config.json')
    return {'vision_mode':os.getenv('REVIEWARENA_VISION','auto'),'model':model,'endpoint_host':endpoint.hostname,'endpoint_port':endpoint.port,'files':{str(p.relative_to(ROOT)):digest(p,p.stat().st_size,p.stat().st_mtime_ns) for p in paths if p.exists()}}
