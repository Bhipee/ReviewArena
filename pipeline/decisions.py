"""Preserve official chair decision notes, with held-out notes isolated from retrieval."""
import json
from pathlib import Path
import duckdb
import pyarrow.parquet as pq
from fetch import RAW,ROOT

DATA=ROOT/'data'


def materialize():
    with duckdb.connect() as db:
        papers=RAW/'papers.parquet'
        notes=RAW/'notes-*.parquet'
        q="""select p.paper_openreview_id paper_id, n.review_openreview_id note_id,
                    split_part(p.venue,'/',2)::integer as year,n.writer,n.title,n.content,n.time
             from read_parquet(?) p join read_parquet(?) n
               on n.replyto_openreview_id=p.paper_openreview_id and n.venue=p.venue
             where p.venue like 'ICLR.cc/%/Conference'
               and (lower(n.writer) like '%chair%' or lower(n.writer) like '%conference%')
               and (lower(n.title) in ('paper decision','final decision','meta review','meta-review')
                    or lower(n.title) like '%conference acceptance decision')
               and split_part(p.venue,'/',2) between ? and ?
             order by paper_id,n.time,n.review_openreview_id"""
        for start,end,folder in [('2018','2023',DATA),('2025','2025',DATA/'iclr2025')]:
            rows=db.execute(q,[str(papers),str(notes),start,end]).arrow().read_all()
            if start=='2025':
                ids={r['id'] for r in json.loads((folder/'manifest.json').read_text())}
                import pyarrow.compute as pc
                import pyarrow as pa
                rows=rows.filter(pc.is_in(rows['paper_id'],value_set=pa.array(sorted(ids))))
            path=folder/'chair_decisions.parquet';tmp=path.with_suffix('.tmp')
            pq.write_table(rows,tmp);tmp.replace(path)
            print(start,end,len(rows),'chair notes for',len(set(rows['paper_id'].to_pylist())),'papers')


if __name__=='__main__':materialize()
