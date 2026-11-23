"""Create and score blind human assessment sheets for the 20-question lab experiment."""
import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import pymupdf
from run import DATA, write
from reviewarena.paper import parse_pdf


def build_rows():
    answers = []
    citations = []
    sources = {}
    for index, reference in enumerate(json.loads(Path(__file__).with_name("lab_qa.json").read_text())):
        raw = (DATA / "eval-lab" / f"{index:02}.json").read_bytes()
        record = json.loads(raw)
        if record["reference"] != reference:
            raise ValueError(f"Changed reference for question {index}")
        sources[index] = hashlib.sha256(raw).hexdigest()
        points = record["rag"]["points"]
        common = dict(question=reference["question"], reference_answer=reference["answer"],
                      reference_page=reference["page"], reference_quote=reference["quote"])
        for method, answer in [("baseline", record["baseline"].get("answer","")),
                               ("rag", "\n".join(p["text"] for p in points))]:
            answers.append((dict(question_index=index, method=method), dict(**common, answer=answer)))
        by_passage = {}
        for point in points:
            for source in point["sources"]:
                key = (source["file"], source["page"], source["id"])
                row = by_passage.setdefault(key, dict(question=reference["question"], file=source["file"],
                         page=source["page"], passage=source["text"], claims=[]))
                if row["passage"] != source["text"]:
                    raise ValueError(f"One passage ID has different text in question {index}")
                if point["text"] not in row["claims"]:
                    row["claims"].append(point["text"])
        for key, row in by_passage.items():
            row["claims"] = "\n".join(row["claims"])
            citations.append((dict(question_index=index, passage_id=key[-1]), row))
    return sources, {"answers": answers, "citations": citations}


def verify_source_pages(folder, sheets):
    references = json.loads(Path(__file__).with_name("lab_qa.json").read_text())
    passages = [(r["paper_id"] + ".pdf", r["page"], r["quote"]) for r in references]
    passages.extend((row["file"], row["page"], row["passage"]) for _, row in sheets["citations"])
    papers = {}
    hashes = {}
    block_matches = 0
    for filename, page, quote in passages:
        if filename not in papers:
            raw = (DATA / "iclr2023" / filename).read_bytes()
            parsed = parse_pdf(raw)
            hashes[filename] = parsed["hash"]
            papers[filename] = (parsed["pages"], raw)
        pages, raw = papers[filename]
        if not quote or not 1 <= page <= len(pages):
            raise ValueError(f"Invalid passage or page in {filename}, p. {page}")
        if quote in pages[page - 1]:
            continue
        # A figure beside a text column can interleave lines in sorted page text.
        with pymupdf.open(stream=raw, filetype="pdf") as doc:
            blocks = doc[page - 1].get_text("blocks")
        if not any(quote in " ".join(b[4].split()) for b in blocks if b[6] == 0):
            raise ValueError(f"Quotation missing from {filename}, p. {page}")
        block_matches += 1
    proof = dict(manuscript_sha256=hashes, references=len(references), citations=len(sheets["citations"]),
                 quotations_requiring_column_blocks=block_matches)
    target = folder / "source-pages.json"
    if target.exists() and json.loads(target.read_text()) != proof:
        raise ValueError("Source PDF or citation inventory differs from the human assessment packet")
    if not target.exists():
        write(target, proof)


def assess(folder, score):
    sources, sheets = build_rows()
    folder.mkdir(parents=True, exist_ok=True)
    verify_source_pages(folder, sheets)
    counts = defaultdict(Counter)
    for kind, rows in sheets.items():
        random.Random(16).shuffle(rows)
        manifest = dict(sources=sources, ids=[meta for meta, _ in rows])
        key = folder / (kind + "-key.json")
        if key.exists() and json.loads(key.read_text()) != json.loads(json.dumps(manifest)):
            raise ValueError("Source or sample changed for " + kind)
        if not key.exists():
            write(key, manifest)
        path = folder / (kind + ".csv")
        expected = [{"sample_id": str(i), **{k:str(v) for k,v in row.items()}} for i, (_,row) in enumerate(rows)]
        if not path.exists():
            with path.open("x", newline="") as out:
                writer = csv.DictWriter(out, fieldnames=[*expected[0], "rating", "reason"])
                writer.writeheader()
                writer.writerows(expected)
        valid = {"correct","partial","incorrect","missing"} if kind=="answers" else {"supports","partially_supports","does_not_support"}
        with path.open(newline="") as src:
            ratings = list(csv.DictReader(src))
        if len(ratings)!=len(rows) or {r["sample_id"] for r in ratings}!={r["sample_id"] for r in expected}:
            raise ValueError("Missing or duplicate sample IDs in " + kind)
        for rated in ratings:
            i = int(rated["sample_id"])
            if any(rated[k]!=v for k,v in expected[i].items()):
                raise ValueError(f"Changed {kind} sample {i}")
            if not score:
                continue
            rating = rated["rating"].strip()
            if rating not in valid or not rated["reason"].strip():
                raise ValueError(f"Incomplete {kind} rating {i}. Allowed values: {sorted(valid)}")
            counts[rows[i][0].get("method", kind)][rating] += 1
    if score:
        write(folder/"summary.json", dict(judge="human", counts=counts))
    print({name:len(rows) for name,rows in sheets.items()}, folder)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder",type=Path,default=DATA/"eval-lab-human")
    parser.add_argument("--score",action="store_true")
    args=parser.parse_args()
    assess(args.folder,args.score)
