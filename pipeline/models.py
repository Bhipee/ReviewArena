"""Download pinned model files at the revision returned by the HF model registry."""
import argparse,requests
from pathlib import Path
from fetch import ROOT,download
def model(repo,directory,names):
    r=requests.get('https://huggingface.co/api/models/'+repo,timeout=20);r.raise_for_status()
    meta=r.json();dest=ROOT/'data'/directory;dest.mkdir(parents=True,exist_ok=True)
    for item in meta['siblings']:
        filename=item['rfilename']
        if names(filename):download((f"https://huggingface.co/{repo}/resolve/{meta['sha']}/{filename}",dest/filename))
    print(repo,meta['sha'])
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--local-llm',action='store_true');args=p.parse_args()
    model('Qdrant/bge-small-en-v1.5-onnx-Q','bge-small',lambda f:f in ('model_optimized.onnx','tokenizer.json'))
    if args.local_llm:model('mlx-community/Qwen2.5-3B-Instruct-4bit','model',lambda f:f.endswith(('.json','.txt','.safetensors','.model')))
