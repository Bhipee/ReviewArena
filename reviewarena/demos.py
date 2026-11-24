"""Read and save completed action results for offline demonstrations."""
import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from .kb import DATA


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def demo_path(action, inputs):
    return DATA / "private" / "demos" / action / (fingerprint(inputs) + ".json")


def save_demo(action, inputs, result):
    path = demo_path(action, inputs)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = NamedTemporaryFile(dir=path.parent, mode="w", delete=False, encoding="utf-8")
    pending = Path(temp.name)
    try:
        with temp:
            json.dump({"inputs": inputs, "result": result}, temp, ensure_ascii=False)
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def load_demo(action, inputs):
    path = demo_path(action, inputs)
    if path.is_file():
        try:
            saved = json.loads(path.read_bytes())
        except (OSError, ValueError):
            return None
        if isinstance(saved, dict) and saved.get("inputs") == inputs:
            return saved.get("result")
    return None


def review_demo_path(paper_hash, venue, before, sample_id=None):
    inputs = [paper_hash, venue, before]
    candidates = [demo_path("review", inputs)]
    if sample_id == "k2ZVAzVeMP":
        candidates.append(DATA / "eval-product-claim-coverage" / sample_id / "D.json")
    if sample_id:
        candidates.append(
            DATA / "eval-product-reviewed-families" / sample_id / "D.json"
        )
    name = f"{paper_hash}-{venue}-{before}.json"
    candidates.extend([DATA / "product-replays" / name, DATA / "replays" / name])
    for path in candidates:
        if not path.is_file():
            continue
        try:
            read_review_demo(path, paper_hash, venue, before)
        except (OSError, KeyError, ValueError, TypeError, AttributeError):
            continue
        return path
    return None


def read_review_demo(path, paper_hash, venue, before):
    data = json.loads(path.read_bytes())
    if "inputs" in data:
        if data["inputs"] != [paper_hash, venue, before]:
            raise ValueError("Saved review is for different inputs.")
        data = data["result"]
    request = {"manuscript_sha256": paper_hash, "before": before}
    if (
        "request" not in data
        and path.parent == DATA / "replays"
        and path.name == f"{paper_hash}-{venue}-{before}.json"
    ):
        data = dict(data, request=request)
    if (
        data.get("venue") != venue
        or data.get("request") != request
        or len(data.get("reviews", [])) not in (3, 5)
        or ("reviewer_panel" in data and data["reviewer_panel"] != [r.get("role") for r in data["reviews"]])
    ):
        raise ValueError(
            "Saved review does not match this manuscript and review request."
        )
    return data


def chair_inputs(inputs, result):
    meta = result["meta_review"]
    decision = meta.get("recommendation")
    evidence = [
        result["reviews"],
        result.get("claims"),
        result.get("contribution_comparisons"),
        result.get("research_value"),
        decision if decision in ("Accept", "Reject") else None,
    ]
    return [*inputs, fingerprint(evidence)]


def reading_from_review(result, paper_hash):
    if not all(k in result for k in ("claims", "paper_type", "settings")):
        return None
    return dict(
        manuscript_sha256=paper_hash,
        **{
            k: result[k]
            for k in ("claims", "paper_type", "settings", "declared_limitations")
            if k in result
        },
    )


def read_scope_demo(paper_hash, review_path=None, venue=None, before=None):
    saved = load_demo("reading", [paper_hash])
    if saved is not None:
        return saved
    path = DATA / "manuscript-replays" / (paper_hash + ".json")
    if path.is_file():
        record = json.loads(path.read_bytes())
        if record["manuscript_sha256"] == paper_hash:
            return dict(record["scope"], manuscript_sha256=paper_hash)
    if review_path:
        return reading_from_review(
            read_review_demo(review_path, paper_hash, venue, before), paper_hash
        )
    return None


def public_lab_result(record, inputs):
    mode, question, files, manuscript, notes = inputs
    sources = dict(record["documents"])
    sources.update(
        {
            name: info["sha256"]
            for name, info in record.get("meeting_records", {}).items()
        }
    )
    if (mode, question, files, manuscript, notes) != (
        record["mode"],
        record["question"],
        sources,
        record.get("manuscript"),
        sorted(record.get("meeting_records", {})),
    ):
        return None
    path = DATA / record["source"]
    if (
        not path.is_file()
        or hashlib.sha256(path.read_bytes()).hexdigest() != record["source_sha256"]
    ):
        return None
    return record["result"]


def summary_inputs(digest, prompt, examples):
    pairs = []
    for example in examples:
        sha = example.get("digest")
        if example.get("content") is not None:
            sha = hashlib.sha256(example["content"]).hexdigest()
        pairs.append([example["summary"], sha])
    return [digest, prompt, pairs]
