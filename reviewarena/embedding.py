from functools import lru_cache
from pathlib import Path
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

@lru_cache(maxsize=1)
def encoder():
    path=Path(__file__).resolve().parents[1]/'data/bge-small'
    tok=Tokenizer.from_file(str(path/'tokenizer.json'))
    tok.enable_truncation(max_length=512);tok.enable_padding()
    options=ort.SessionOptions();options.intra_op_num_threads=2
    model=ort.InferenceSession(str(path/'model_optimized.onnx'),options,providers=['CPUExecutionProvider'])
    return tok,model

def embed(texts):
    tok,model=encoder()
    vectors=[]
    for start in range(0,len(texts),32):
        batch=tok.encode_batch(texts[start:start+32])
        inputs={'input_ids':np.asarray([b.ids for b in batch],dtype=np.int64),'attention_mask':np.asarray([b.attention_mask for b in batch],dtype=np.int64),'token_type_ids':np.asarray([b.type_ids for b in batch],dtype=np.int64)}
        output=model.run(None,{i.name:inputs[i.name] for i in model.get_inputs()})[0]
        v=output[:,0] if output.ndim==3 else output
        vectors.append(v/np.maximum(np.linalg.norm(v,axis=1,keepdims=True),1e-9))
    return np.concatenate(vectors)
