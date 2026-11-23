"""Count the complete source archive by year without admitting held-out notes to retrieval."""
import json
from pathlib import Path
import duckdb

from fetch import RAW, ROOT


def main():
    with duckdb.connect() as db:
        db.execute("""create temp table papers as select paper_openreview_id id,venue,split_part(venue,'/',2)::int as year
                    from read_parquet(?) where venue like 'ICLR.cc/%/Conference' and split_part(venue,'/',2) between '2018' and '2025'""",
                   [str(RAW/'papers.parquet')])
        db.execute("""create temp table notes as select review_openreview_id id,replyto_openreview_id as parent,venue,
                    lower(title) as title, lower(writer) as writer from read_parquet(?) where venue in (select distinct venue from papers)""",[str(RAW/'notes-*.parquet')])
        db.execute("""create temp table reviews as select n.id,p.year from notes n join papers p
                   on n.venue=p.venue and n.parent=p.id where n.title like '%official review%'""")
        counts=db.execute("""select year, count(*) papers,
               (select count(*) from reviews where year=p.year) official_reviews,
               (select count(*) from notes n join reviews r on n.parent=r.id where r.year=p.year and n.writer like '%author%') direct_author_replies,
               (select count(*) from notes n join papers q on n.venue=q.venue and n.parent=q.id where q.year=p.year
               and (n.writer like '%chair%' or n.writer like '%conference%') and (n.title in ('paper decision','final decision','meta review','meta-review')
               or n.title like '%conference acceptance decision')) chair_notes
               from papers p group by year order by year""").fetchall()
    fields=['year','papers','official_reviews','direct_author_replies','chair_notes']
    rows=[dict(zip(fields,row)) for row in counts]
    totals={key:sum(r[key] for r in rows) for key in fields[1:]}
    training={key:sum(r[key] for r in rows if r['year']<=2023) for key in fields[1:]}
    with duckdb.connect(str(ROOT/'data/history.duckdb'),read_only=True) as db:
        assert tuple(training[key] for key in fields[1:4])==db.sql(
            'select (select count(*) from papers),(select count(*) from reviews),(select count(*) from replies)').fetchone()
    target=ROOT/'data/metrics/archive-inventory.json'
    tmp=target.with_suffix('.tmp')
    tmp.write_text(json.dumps(dict(by_year=rows,whole_archive=totals,historical_split=training),indent=2))
    tmp.replace(target)
    print('2018–2025',totals,'2018–2023',training)


if __name__=='__main__':main()
