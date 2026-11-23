"""Store reusable embeddings of the public, ordered review passages."""
import hashlib
import json
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np

from .embedding import embed

DATA=Path(__file__).resolve().parents[1]/'data'


@lru_cache(maxsize=1)
def encoder_digest(files):
    digest=hashlib.sha256()
    for path,_,_ in files:
        with path.open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):
                digest.update(block)
    return digest.digest()


def passage_vectors(rows,field,publish=False):
    texts=[r[field] for r in rows]
    files=[DATA/'bge-small/model_optimized.onnx',DATA/'bge-small/tokenizer.json',Path(__file__).with_name('embedding.py')]
    stamps=tuple((p,p.stat().st_size,p.stat().st_mtime_ns) for p in files)
    payload=json.dumps(texts,ensure_ascii=False,separators=(',',':')).encode()
    digest=hashlib.sha256(encoder_digest(stamps)+payload).hexdigest()
    cache=DATA/'review-vectors'/(field+'-'+digest+'.npy')
    if cache.is_file():
        try:
            array=np.load(cache,mmap_mode='r',allow_pickle=False)
            if array.ndim==2 and array.shape[0]==len(texts) and array.dtype==np.float32:
                return array
        except (OSError,ValueError,EOFError):
            pass
    vectors=embed(texts)
    if publish:
        cache.parent.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cache.parent,delete=False) as output:
            np.save(output,vectors,allow_pickle=False)
            tmp=Path(output.name)
        tmp.replace(cache)
    return vectors
