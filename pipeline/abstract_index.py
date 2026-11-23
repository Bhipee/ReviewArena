"""Persist BGE vectors for all historical papers for the whole-paper baseline."""
from pathlib import Path
import sys,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reviewarena.embedding import embed
from reviewarena.kb import DATA
import duckdb,numpy as np
def main():
    with duckdb.connect(str(DATA/'history.duckdb'),read_only=True) as db:
        rows=db.sql("select id,coalesce(title,'')||' '||coalesce(abstract,'') from papers order by id").fetchall()
    vectors=[]
    shard=DATA/'abstract_vectors';shard.mkdir(exist_ok=True)
    for start in range(0,len(rows),128):
        part=shard/f'{start}.npy'
        if not part.exists():
            mat=embed([text for _,text in rows[start:start+128]])
            with part.with_suffix('.tmp').open('wb') as f:np.save(f,mat)
            part.with_suffix('.tmp').replace(part)
        vectors.append(np.load(part))
    tmp=DATA/'paper_vectors.tmp.npz'
    np.savez(tmp,ids=[r[0] for r in rows],vectors=np.concatenate(vectors))
    tmp.replace(DATA/'paper_vectors.npz')
if __name__=='__main__':main()
