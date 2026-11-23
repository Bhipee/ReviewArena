"""Fetch public ResearchArcade OpenReview snapshots, using atomic downloads."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw"

def download(item):
    url, path = item
    if path.exists():
        return
    tmp = path.with_suffix(".part")
    with requests.get(url, stream=True, timeout=(15, 90)) as response:
        response.raise_for_status()
        with tmp.open("wb") as out:
            for chunk in response.iter_content(1024 * 1024):
                out.write(chunk)
    tmp.replace(path)
    print(path.name, path.stat().st_size, flush=True)

if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    base = "https://huggingface.co/datasets/"
    files = [(base + f"ulab-ai/ResearchArcade-openreview-reviews/resolve/main/data/train-{i:05d}-of-00006.parquet", RAW / f"notes-{i}.parquet") for i in range(6)]
    files += [(base + "ulab-ai/ResearchArcade-openreview-papers/resolve/main/data/train-00000-of-00001.parquet", RAW / "papers.parquet"),
              (base + "smallari/openreview-iclr-peer-reviews/resolve/main/data/raw-00000-of-00001.parquet", RAW / "reviews.parquet")]
    with ThreadPoolExecutor(3) as pool:
        list(pool.map(download, files))
