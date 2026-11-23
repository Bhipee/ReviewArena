"""Prepare offline Manuscript review actions for one PDF and venue."""
import argparse
import asyncio
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reviewarena.claims import declared_limitations
from reviewarena.demos import (
    chair_inputs,
    load_demo,
    read_review_demo,
    read_scope_demo,
    review_demo_path,
    save_demo,
)
from reviewarena.kb import DATA
from reviewarena.paper import parse_pdf
from reviewarena.workflow import chair_recommendation, inspect_manuscript, run_review


async def main(args):
    paper = parse_pdf(args.pdf.read_bytes())
    sha = paper["hash"]
    before = args.before.isoformat()
    inputs = [sha, args.venue, before]
    path = review_demo_path(*inputs, sample_id=args.pdf.stem)
    scope = None if args.refresh else read_scope_demo(sha, path, args.venue, before)
    if scope is None:
        claims, kind, settings = await inspect_manuscript(paper)
        scope = dict(
            manuscript_sha256=sha,
            claims=claims,
            paper_type=kind,
            settings=settings,
            declared_limitations=declared_limitations(paper),
        )
    save_demo("reading", [sha], scope)
    print("Manuscript reading ready.", flush=True)
    if path is None or args.refresh:
        result = await run_review(
            paper,
            args.venue,
            before=before,
            prepared_reading=scope,
            on_stage=lambda stage: print(stage["label"], flush=True),
        )
    else:
        result = read_review_demo(path, *inputs)
    chair_key = chair_inputs(inputs, result)
    chair = result["meta_review"]
    if chair.get("rationale_version") != 2:
        chair = load_demo("chair", chair_key) or await chair_recommendation(
            args.venue,
            result["reviews"],
            result.get("claims"),
            decision=chair.get("recommendation"),
            novelty=result.get("contribution_comparisons"),
            research_value=result.get("research_value"),
        )
    if (
        chair.get("recommendation") not in ("Accept", "Reject")
        or chair.get("rationale_version") != 2
    ):
        raise ValueError("The saved review needs a complete chair recommendation.")
    save_demo("chair", chair_key, chair)
    result["meta_review"] = chair
    save_demo("review", inputs, result)
    print(
        f"Three reviewers and AC ready for {args.pdf.name} · {args.venue} · {before}.",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "pdf", type=Path, nargs="?", default=DATA / "iclr2025/k2ZVAzVeMP.pdf"
    )
    parser.add_argument("--venue", choices=["ICLR", "NeurIPS"], default="ICLR")
    parser.add_argument("--before", type=date.fromisoformat, default=date(2024, 10, 1))
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Regenerate the manuscript reading and three reviews.",
    )
    asyncio.run(main(parser.parse_args()))
