"""Prepare the public examples used by the three workspaces with the local model."""
import asyncio
import hashlib
import json
import sys
from datetime import date
from pathlib import Path
from argparse import Namespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_review_demo import main as prepare_review
from reviewarena.comparison_reader import inspect_comparison
from reviewarena.demos import load_demo, public_lab_result, save_demo, summary_inputs
from reviewarena.kb import DATA
from reviewarena.paper import parse_pdf
from reviewarena.paper_summary import DEFAULT_PROMPT, summarize
from reviewarena.workflow import ask, rebuttal


async def main():
    sample = DATA / "iclr2025/k2ZVAzVeMP.pdf"
    before = date(2024, 10, 1)
    await prepare_review(
        Namespace(pdf=sample, venue="ICLR", before=before, refresh=False)
    )
    paper = parse_pdf(sample.read_bytes())
    comment = json.loads((DATA / "truth-labels/k2ZVAzVeMP.json").read_bytes())[0][
        "quote"
    ]
    inputs = [paper["hash"], hashlib.sha256(comment.encode()).hexdigest()]
    works_inputs = [*inputs, before.isoformat()]
    if load_demo("works", works_inputs) is None:
        save_demo(
            "works",
            works_inputs,
            await inspect_comparison(paper, comment, before.isoformat(), ask),
        )
    if load_demo("reply", inputs) is None:
        bundled = DATA / "rebuttal-replays" / ("-".join(inputs) + ".json")
        saved = json.loads(bundled.read_bytes()) if bundled.is_file() else {}
        reply = (
            saved.get("result")
            if [saved.get("manuscript_sha256"), saved.get("review_sha256")] == inputs
            else None
        )
        save_demo("reply", inputs, reply or await rebuttal(paper, comment))
    print("Rebuttal: works check and point-by-point reply ready.", flush=True)
    auto_cot = parse_pdf((DATA / "iclr2023/5NTt8GFjUHkr.pdf").read_bytes())
    inputs = summary_inputs(auto_cot["hash"], DEFAULT_PROMPT, [])
    if load_demo("summary", inputs) is None:
        save_demo("summary", inputs, summarize(auto_cot, DEFAULT_PROMPT, []))
    print("Paper summary: Auto-CoT with default instructions ready.", flush=True)
    for task in ("question", "related-work-gap", "reviewer-2", "weekly-brief"):
        record = json.loads((DATA / "lab-replays" / (task + ".json")).read_bytes())
        files = {
            name: hashlib.sha256((DATA / "iclr2023" / name).read_bytes()).hexdigest()
            for name in record["documents"]
        }
        notes = record.get("meeting_records", {})
        files.update(
            {
                name: hashlib.sha256((DATA / n["path"]).read_bytes()).hexdigest()
                for name, n in notes.items()
            }
        )
        inputs = [
            task,
            record["question"],
            files,
            record.get("manuscript"),
            sorted(notes),
        ]
        result = public_lab_result(record, inputs)
        if result is None:
            raise ValueError(
                f"Public lab example differs from the saved {task} result."
            )
        save_demo("lab", inputs, result)
        print(f"Lab meeting: {task} ready.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
