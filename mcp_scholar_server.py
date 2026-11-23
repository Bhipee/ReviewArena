import hashlib,json,re,sqlite3,time
from contextlib import closing
from pathlib import Path
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from difflib import SequenceMatcher
import requests
from mcp.server.fastmcp import FastMCP
server=FastMCP("Scholar")

def normalize(text):
    return ' '.join(re.findall(r'[a-z0-9]+',text.lower()))

def _search_papers(query:str,before:str="",limit:int=3,topic:bool|None=None)->list:
    """Find dated publications. Only exact or near-exact title matches verify a named work."""
    cutoff=date.fromisoformat(before) if before else date.max
    records=[]
    try:
        terms=re.findall(r"[a-zA-Z0-9-]+",query)[:8]
        search=" AND ".join("all:"+term for term in terms) if topic else ('ti:' if topic is False else 'all:')+'"'+query.replace('"','')+'"'
        last=(cutoff-timedelta(days=1)).strftime('%Y%m%d')
        response=requests.get("https://export.arxiv.org/api/query",params={"search_query":f"({search}) AND submittedDate:[190001010000 TO {last}2359]","max_results":10},timeout=12)
        response.raise_for_status()
        ns={"a":"http://www.w3.org/2005/Atom"}
        for entry in ET.fromstring(response.content).findall("a:entry",ns):
            def field(key):return " ".join(entry.findtext("a:"+key,"",ns).split())
            records.append(dict(title=field("title"),url=field("id"),published=field("published")[:10],abstract=field("summary"),first_author=entry.findtext("a:author/a:name","",ns),updated=field("updated")[:10],catalog="arXiv"))
    except (requests.RequestException,ET.ParseError):pass
    if topic or not any(r['published'] and r['published']<cutoff.isoformat() for r in records):
        try:
            response=requests.get("https://api.openalex.org/works",params={'search':query,'per_page':min(max(3,limit),10),'filter':'to_publication_date:'+(cutoff-timedelta(days=1)).isoformat(),'select':'id,doi,title,publication_date,abstract_inverted_index,authorships'},timeout=15)
            response.raise_for_status()
            for item in response.json().get('results',[]):
                words=sorted((pos,word) for word,positions in (item.get('abstract_inverted_index') or {}).items() for pos in positions)
                records.append(dict(title=item.get('title') or '',url=item.get('doi') or item['id'],
                                    published=item.get('publication_date'),first_author=next((a['author']['display_name'] for a in (item.get('authorships') or []) if a.get('author',{}).get('display_name')),''),abstract=' '.join(word for _,word in words),catalog="OpenAlex"))
        except requests.RequestException:
            if not records:raise
    out=[]
    for item in records:
        if item['published'] and date.fromisoformat(item['published'])<cutoff:
            item['named_work_verified']=SequenceMatcher(None,normalize(query),normalize(item['title'])).ratio()>=.96
            out.append(item)
    return out[:max(1,min(limit,10))]

SCHOLAR_CACHE=Path(__file__).resolve().parent/'data/private/scholar.sqlite3'

@server.tool()
def search_papers(query:str,before:str="",limit:int=3,topic:bool|None=None)->list:
    """Find dated publications; return cache provenance with each real bibliographic record."""
    if not query.strip():return []
    if before:date.fromisoformat(before)
    limit=max(1,min(limit,10))
    key=hashlib.sha256(json.dumps(['abstracts-v4',query.strip(),before,limit,topic]).encode()).hexdigest()
    return cached_lookup(key,lambda:_search_papers(query,before,limit,topic))


def cached_lookup(key,lookup):
    SCHOLAR_CACHE.parent.mkdir(parents=True,exist_ok=True)
    now=int(time.time())
    with closing(sqlite3.connect(SCHOLAR_CACHE)) as db,db:
        db.execute('create table if not exists results(key text primary key, fetched integer not null, records text not null)')
        row=db.execute('select fetched,records from results where key=?',(key,)).fetchone()
    if row and now-row[0]<86400:
        return [dict(r,lookup='cached',fetched_at=row[0]) for r in json.loads(row[1])]
    try:records=lookup()
    except requests.RequestException:
        if row:return [dict(r,lookup='offline cache',fetched_at=row[0]) for r in json.loads(row[1])]
        raise
    if records:
        with closing(sqlite3.connect(SCHOLAR_CACHE)) as db,db:
            db.execute('insert or replace into results values(?,?,?)',(key,now,json.dumps(records)))
    return [dict(r,lookup='live',fetched_at=now) for r in records]


@server.tool()
def resolve_paper_title(title:str,before:str)->list:
    """Resolve a full title and require an exact normalized title match before the cutoff."""
    cutoff=date.fromisoformat(before)
    query=normalize(title)
    if not query:return []
    local=Path(__file__).resolve().parent/'data/publication-records'/(hashlib.sha256(query.encode()).hexdigest()+'.json')
    if local.exists():
        record=json.loads(local.read_bytes())
        if normalize(record['title'])==query and date.fromisoformat(record['published'])<cutoff:
            return [dict(**record,lookup='archived official record',named_work_verified=True)]
    key=hashlib.sha256(json.dumps(['resolve_title',query,before]).encode()).hexdigest()
    def lookup():
        try:
            response=requests.get('https://api.openalex.org/works',params={
                'filter':'title.search:'+query+',to_publication_date:'+before,'per_page':10,
                'select':'id,doi,title,publication_date'},timeout=15)
            response.raise_for_status()
            for item in response.json().get('results',[]):
                published=item.get('publication_date')
                if normalize(item.get('title') or '')==query and published and date.fromisoformat(published)<cutoff:
                    return [dict(title=item['title'],url=item.get('doi') or item['id'],published=published,
                                 abstract='',catalog='OpenAlex',named_work_verified=True)]
        except requests.RequestException:
            pass
        return [r for r in search_papers(title,before,5) if normalize(r['title'])==query]
    return cached_lookup(key,lookup)

@server.tool()
def get_abstract(arxiv_id:str)->dict:
    if not re.fullmatch(r'\d{4}\.\d{4,5}(v\d+)?',arxiv_id):raise ValueError("Invalid arXiv ID")
    r=requests.get('https://export.arxiv.org/api/query',params={'id_list':arxiv_id},timeout=15);r.raise_for_status()
    entry=ET.fromstring(r.content).find('{http://www.w3.org/2005/Atom}entry')
    if entry is None:return {}
    atom='{http://www.w3.org/2005/Atom}'
    return {k:' '.join(entry.findtext(atom+k,'').split()) for k in ('title','id','summary','published')}

@server.tool()
def read_prior_passages(arxiv_id:str,keywords:str)->list:
    """Return exact excerpts and PDF page numbers from the first published arXiv version."""
    import pymupdf
    if not re.fullmatch(r'\d{4}\.\d{4,5}',arxiv_id):
        return []
    url=f'https://arxiv.org/pdf/{arxiv_id}v1'
    def lookup():
        terms=set(re.findall(r'[a-z0-9-]{3,}',keywords.lower()))
        passages=[]
        with requests.get(url,stream=True,timeout=(8,18)) as response:
            response.raise_for_status()
            data=bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data)>20_000_000:return []
        if not data.startswith(b'%PDF'):return []
        with pymupdf.open(stream=bytes(data),filetype='pdf') as pdf:
            for page in pdf:
                end=False
                for raw in page.get_text('blocks'):
                    if raw[6]!=0:continue
                    body=re.split(r'(?im)^\s*(?:\d+\s+)?(?:references|bibliography)\s*$',raw[4],maxsplit=1)
                    text=' '.join(body[0].split())
                    for sentence in re.split(r'(?<!et al\.)(?<=[.!?])\s+(?=[A-Z(])',text):
                        if 45<=len(sentence)<=550:
                            words=set(re.findall(r'[a-z0-9-]{3,}',sentence.lower()))
                            score=len(terms & words)
                            if score>=2:passages.append((score,page.number+1,sentence))
                    if len(body)>1:
                        end=True
                        break
                if end:break
        passages.sort(key=lambda row:-row[0])
        return [dict(page=n,quote=text,url=url) for _,n,text in passages[:6]]
    key=hashlib.sha256(json.dumps(['prior-passages-v2',arxiv_id,keywords]).encode()).hexdigest()
    return cached_lookup(key,lookup)

if __name__=="__main__":server.run()
