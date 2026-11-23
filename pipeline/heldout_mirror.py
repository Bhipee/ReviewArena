"""Find individual submission files in the public ICLR ZIP mirror using HTTP byte ranges."""
import argparse
import hashlib
import io
import json
import re
import struct
import tempfile
import unicodedata
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import pymupdf
import requests

from fetch import RAW, ROOT

DATA = ROOT / 'data'
REPO = 'simon123905/iclr2025_all_zips'


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',text).casefold() if c.isalnum())


def fetch_range(url, spec):
    with requests.get(url, params={'range':spec}, headers={'Range':'bytes='+spec}, stream=True, timeout=(15,60)) as response:
        response.raise_for_status()
        if response.status_code != 206:
            raise ValueError('Mirror did not honor requested byte range')
        content = response.content
        m = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers['Content-Range'])
        start,end,size = map(int,m.groups())
        if len(content)!=end-start+1 or (not spec.startswith('-') and start!=int(spec.split('-')[0])):
            raise ValueError('Unexpected mirror response range')
        return content, size


def archive_entries(archive):
    filename=archive['path']
    url='https://huggingface.co/datasets/'+REPO+'/resolve/main/'+filename
    tail,size=fetch_range(url,'-65536')
    eocd=zipfile._EndRecData(io.BytesIO(tail))
    if eocd is None:
        raise ValueError('Missing ZIP directory for '+filename)
    length=eocd[zipfile._ECD_SIZE]
    end_start=tail.rfind(zipfile.stringEndArchive64)
    if end_start<0:
        end_start=tail.rfind(zipfile.stringEndArchive)
    directory_start=size-len(tail)+end_start-length
    data,_=fetch_range(url,f'{directory_start}-{size-1}')
    # ZipFile adjusts absolute offsets when reading a partial archive. Use the original
    # offsets by placing the small directory at its original position in a sparse file.
    with tempfile.TemporaryFile() as tmp:
        tmp.seek(directory_start)
        tmp.write(data)
        with zipfile.ZipFile(tmp) as z:
            return [(i.filename,i.header_offset,i.compress_size,i.file_size,i.CRC,url) for i in z.infolist()]


def extract(entry):
    name,offset,compressed,size,crc,url=entry
    header,_=fetch_range(url,f'{offset}-{offset+29}')
    if header[:4]!=b'PK\x03\x04':
        raise ValueError('Wrong local header for '+name)
    name_length,extra_length=struct.unpack_from('<HH',header,26)
    start=offset+30+name_length+extra_length
    body,_=fetch_range(url,f'{start}-{start+compressed-1}')
    method=struct.unpack_from('<H',header,8)[0]
    decompressor=zipfile._get_decompressor(method)
    raw=decompressor.decompress(body) if decompressor else body
    if len(raw)!=size or zipfile.crc32(raw)!=crc:
        raise ValueError('ZIP checksum mismatch for '+name)
    return raw


def main(late=False):
    folder=DATA/'heldout-version-audit'
    folder.mkdir(exist_ok=True)
    manifest=json.loads((DATA/'iclr2025/manifest.json').read_bytes())
    targets={}
    for paper in manifest:
        with pymupdf.open(DATA/'iclr2025'/(paper['id']+'.pdf')) as pdf:
            if (late and paper.get('timing_audit')=='PDF created on or after first review') or normalize(paper['title']) not in normalize(pdf[0].get_text()[:2300]):
                targets[normalize(paper['title'])]=paper
    response=requests.get('https://huggingface.co/api/datasets/'+REPO+'/tree/main',params={'limit':1000},timeout=30)
    response.raise_for_status()
    archives=[a for a in response.json() if a['path'].endswith('.zip')]
    with ThreadPoolExecutor(4) as pool:
        for entries in pool.map(archive_entries,archives):
            by_name={entry[0]:entry for entry in entries}
            for entry in entries:
                name=entry[0]
                if not name.lower().endswith('.pdf'):continue
                paper=targets.get(normalize(Path(name).stem))
                if not paper:continue
                pid=paper['id']
                source=folder/(pid+'.pdf')
                raw=source.read_bytes() if source.exists() else extract(entry)
                metadata_entry=by_name.get(name[:-4]+'.json')
                companion=json.loads(extract(metadata_entry)) if metadata_entry else None
                if companion:
                    (folder/(pid+'.mirror-note.json')).write_text(json.dumps(companion,ensure_ascii=False))

                with pymupdf.open(stream=raw,filetype='pdf') as doc:
                    if normalize(paper['title']) not in normalize(doc[0].get_text()[:2300]):continue
                    pages=len(doc)
                with duckdb.connect() as db:
                    link=db.execute('select paper_pdf_link from read_parquet(?) where paper_openreview_id=?',[str(RAW/'papers.parquet'),pid]).fetchone()[0]
                digest=hashlib.sha1(raw).hexdigest()
                metadata=dict(id=pid,title=paper['title'],archive=entry[-1],entry=name,
                              pages=pages,sha256=hashlib.sha256(raw).hexdigest(),sha1=digest,
                              official_pdf_path=link,official_hash_matches=digest==Path(link).stem)
                (folder/(pid+'.pdf')).write_bytes(raw)
                (folder/(pid+'.json')).write_text(json.dumps(metadata,indent=2))
                print(pid,pages,metadata['official_hash_matches'],name,flush=True)
    print('Audited',len(archives),'archives for',len(targets),'manuscripts',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--late',action='store_true')
    main(parser.parse_args().late)
