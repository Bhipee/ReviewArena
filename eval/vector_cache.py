"""Measure passage encoding and verified cache loading for one immutable corpus snapshot."""
from time import perf_counter

import numpy as np
import pyarrow.parquet as pq
from run import DATA,write
from reviewarena.embedding import embed,encoder
from reviewarena.kb import current_snapshot
from reviewarena.review_vectors import passage_vectors


def benchmark():
    snapshot=current_snapshot()
    rows=pq.read_table(snapshot/'critique.parquet').to_pylist()
    encoder()
    result={}
    for field in ('trigger_text','critique_text'):
        started=perf_counter()
        loaded=passage_vectors(rows,field)
        if not isinstance(loaded,np.memmap):raise RuntimeError('Build the offline review index before benchmarking')
        cached=loaded.copy()
        read_seconds=perf_counter()-started
        started=perf_counter()
        original=embed([r[field] for r in rows])
        encode_seconds=perf_counter()-started
        difference=float(np.max(np.abs(cached-original)))
        if not np.array_equal(cached,original):raise ValueError(f'{field} vectors differ by {difference}')
        result[field]=dict(rows=len(rows),dimensions=cached.shape[1],read_seconds=read_seconds,
                           encode_seconds=encode_seconds,max_abs_difference=difference)
    write(DATA/'metrics/review-vector-load.json',dict(snapshot=snapshot.name,fields=result))
    print(result)


if __name__=='__main__':
    benchmark()
