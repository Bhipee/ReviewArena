import hashlib,json,re,sqlite3,time
from contextlib import closing
from pathlib import Path
import xml.etree.ElementTree as ET
from datetime import date
from difflib import SequenceMatcher
import requests
from mcp.server.fastmcp import FastMCP
server=FastMCP("Scholar")

def normalize(text):
    return ' '.join(re.findall(r'[a-z0-9]+',text.lower()))

def _search_papers(query:str,before:str="",limit:int=3)->list:
    """Find dated publications. Only exact or near-exact title matches verify a named work."""
    cutoff=date.fromisoformat(before) if before else date.max
    records=[]
    try:
        response=requests.get("https://export.arxiv.org/api/query",params={"search_query":'all:"'+query.replace('"','')+'"',"max_results":10},timeout=12)
        response.raise_for_status()
        ns={"a":"http://www.w3.org/2005/Atom"}
        for entry in ET.fromstring(response.content).findall("a:entry",ns):
            def field(key):return " ".join(entry.findtext("a:"+key,"",ns).split())
            records.append(dict(title=field("title"),url=field("id"),published=field("published")[:10],abstract=field("summary"),catalog="arXiv"))
    except (requests.RequestException,ET.ParseError):pass
    if not any(r['published'] and r['published']<cutoff.isoformat() for r in records):
        response=requests.get("https://api.openalex.org/works",params={'search':query,'per_page':min(max(3,limit),10),'filter':'to_publication_date:'+cutoff.isoformat(),'select':'id,doi,title,publication_date'},timeout=15)
        response.raise_for_status()
        for item in response.json().get('results',[]):
            records.append(dict(title=item.get('title') or '',url=item.get('doi') or item['id'],published=item.get('publication_date'),abstract='',catalog="OpenAlex"))
    out=[]
    for item in records:
        if item['published'] and date.fromisoformat(item['published'])<cutoff:
            item['named_work_verified']=SequenceMatcher(None,normalize(query),normalize(item['title'])).ratio()>=.96
            out.append(item)
    return out[:max(1,min(limit,10))]

SCHOLAR_CACHE=Path(__file__).resolve().parent/'data/private/scholar.sqlite3'

@server.tool()
def search_papers(query:str,before:str="",limit:int=3)->list:
    """Find dated publications; return cache provenance with each real bibliographic record."""
    if not query.strip():return []
    if before:date.fromisoformat(before)
    limit=max(1,min(limit,10))
    key=hashlib.sha256(json.dumps([query.strip(),before,limit]).encode()).hexdigest()
    return cached_lookup(key,lambda:_search_papers(query,before,limit))


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
if __name__=="__main__":server.run()
