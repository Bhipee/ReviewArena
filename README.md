# ReviewArena · COMP6708 Group 16

A training-free review workbench for authors and supervisors. Upload a manuscript, retrieve historical reviewer concerns triggered by similar passages, and inspect the supporting or countervailing evidence from the current PDF. The rebuttal and research-group workspaces reuse the same document and literature tools.

## Run the prepared checkout

On this Apple Silicon demo machine, the weights, virtual environment, historical snapshot and evaluation documents are under this project. Start the model and UI in separate terminals.

When copying the prepared project to another machine, include the `data/` and `.evaluation-runtime/` directories and preserve symlinks. Create a fresh environment on the destination using Python 3.11. From the project directory run:

    python3.11 -m venv .venv
    .venv/bin/python -m pip install -r demo/requirements.txt

The local MLX server requires Apple Silicon. For an external inference endpoint, configure the variables below and start only the UI. To use the included model downloader on Apple Silicon, run `.venv/bin/python pipeline/models.py --local-llm`.

    ./start_model.sh
    ./run.sh --server.port 8516

Open http://127.0.0.1:8516. The local model listens on 127.0.0.1:8766. To use an OpenAI-compatible server, put the following settings in the project-root `.env` and start the UI with `REVIEWARENA_BACKEND=configured ./run.sh --server.port 8516`. The standard launcher always selects the local Qwen endpoint, including when online credentials are present.

    REVIEWARENA_API_URL=https://your-provider.example/v1
    REVIEWARENA_MODEL=your-model-id
    REVIEWARENA_API_KEY=your-api-key

Upload only material authorized for that endpoint. The arXiv tool receives a search query, not the manuscript.

## Data and model provenance

| Component | Source and scope |
|---|---|
| Historical corpus | ResearchArcade OpenReview public papers and threaded reviews, restricted by venue and year to ICLR 2018–2023. The application counts papers and official reviews directly in DuckDB. |
| Live paper comparisons | All available conference years with usable official reviews in the ResearchArcade snapshot, supplemented by the [ICLR 2020–2026 OpenReview note archive](https://github.com/qhjqhj00/iclr-openreview-reviews/releases/tag/v1.0). Store its release asset at `data/raw/iclr-openreview-2020-2026.tar.bz2` (SHA256 `350071daf25ebf1aef854ee1d5dc3a81834e1c468917c82a4f78af5548de34fc`). The index merges by OpenReview paper and review IDs. Rebuild with `.venv/bin/python pipeline/comparison_pool.py`. Search title and abstract across venues, select a public review excerpt, and apply the review-date cutoff. The verified passage index and frozen experiments have separate coverage. |
| Historical PDFs | Public ICLR mirrors and title-matched arXiv versions. Each imported source carries a page count and version record. Availability favors accepted papers and manuscripts with public preprints. |
| Evidence labels | gpt-6-luna at xhigh. Import checks the quoted review, paper, page and reply ID before a pair enters retrieval. The full historical review count and the indexed pair count are different quantities. |
| Held-out papers | The ICLR 2025 manifest contains 25 accepted and 25 rejected papers. Each primary PDF has a first-page title check, SHA256 and timing audit. A separate 30-paper cohort has pre-review PDFs. Some primary copies were generated after reviewing began. |
| Model | Local mlx-community/Qwen2.5-3B-Instruct-4bit for inference; Qdrant/bge-small-en-v1.5-onnx-Q for retrieval. No model training. |
| Research group | Four public papers stand in for private group documents for the classroom example. Users can supply their own PDFs or Markdown notes. |

Sources: [ResearchArcade papers](https://huggingface.co/datasets/ulab-ai/ResearchArcade-openreview-papers), [reviews](https://huggingface.co/datasets/ulab-ai/ResearchArcade-openreview-reviews), [paper–arXiv mapping](https://huggingface.co/datasets/ulab-ai/ResearchArcade-openreview-arxiv), [ICLR 2025 ground truth snapshot](https://huggingface.co/datasets/smallari/openreview-iclr-peer-reviews), [historical PDF mirror](https://huggingface.co/datasets/SlowGuess/ICLR_2023_OCR), [held-out PDF mirror](https://huggingface.co/datasets/SlowGuess/ICLR_2025_OCR).

## Rebuild the data

Use Python 3.11 and install requirements.txt. Apple Silicon local serving additionally needs mlx-lm. Fetch the MLX model snapshot and place it in data/model; place model_optimized.onnx and tokenizer.json from the BGE repository in data/bge-small.

    python pipeline/fetch.py
    python pipeline/papers.py 2023 1000
    python pipeline/papers.py 2025 50
    python pipeline/heldout.py
    python pipeline/prepare.py
    python pipeline/import_labels.py data/labels
    python pipeline/abstract_index.py

OpenReview API access from this deployment returned a human-verification challenge. The downloader therefore uses the public snapshots above. No test review is indexed. The whole-corpus classifier resumes from verified review packets (`python pipeline/classify.py --limit 1`). It uses gpt-6-luna at xhigh and checks source hashes and all review IDs before admitting labels. The ChatGPT-account Codex CLI on the demonstration machine returned model_not_found for that model. Desktop labeling uses the requested model and effort, and the same packet importer. Unconfirmed post-rebuttal resolution is stored as unknown.

Detailed manuscript labeling uses `python pipeline/label.py --limit 10`. Each slot goes to the available year with the fewest previously reviewed manuscripts. Existing verified files, including reviewed manuscripts with zero linked issues, count toward that year on resume. The archived PDF inventory limits how many examples each year can contribute.

## Evaluation and reproduction

    python eval/run.py --paper k2ZVAzVeMP --methods ABCD
    python eval/run.py --methods ABCD
    python eval/lab.py

A reads manuscript notes; B adds historical reviews retrieved by paper similarity; C uses passage-trigger retrieval; D verifies candidate concerns against the current paper, including appendices, and calls the literature tool. Run outputs are stored per method and paper. Only completed runs can be replayed. Historical acceptance among matched papers is a descriptive cohort statistic; the selected PDF mirror and limited labels prevent a calibrated prediction.

The two MCP servers support stdio transport. Start either entry point with the project Python interpreter: mcp_reviewkb_server.py or mcp_scholar_server.py. See docs/ for the original proposals and course rubric.

The lab workspace can retain uploaded PDFs and notes in a local, versioned SQLite library. Select “Save uploads to local lab library” to make them available in later sessions. Related-work checks scan the chosen draft for each retrieved title and display matching page numbers. Bibliographic lookups distinguish live results from cached records.

The pilot semantic judgments under data/judgments are bound to the exact per-method input packets by SHA256. Run `python eval/metrics.py` for the pilot or `python eval/metrics.py --run eval-frozen` for the main run. Under Corpus, the live four-method table reports the number of fully paired manuscripts, their decision mix, and the denominators for predictions and reviewer concerns. The classroom backup recording is in `demo/ReviewArena_replay.mp4`.


The held-out issue set contains 1,047 passage-verified labels from 50 papers. The full comparison runs sequentially against fixed copies of the two annotation indexes:

    PROJECT_DIR="$PWD"
    (cd "$PROJECT_DIR/.evaluation-runtime/baseline-v1" && REVIEWARENA_KB_SNAPSHOT="$PROJECT_DIR/data/eval-frozen/indexes" REVIEWARENA_RUN_NAMESPACE=eval-frozen "$PROJECT_DIR/.venv/bin/python" eval/run.py --methods ABCD)
    python eval/metrics.py --run eval-frozen

The group-workspace assessment uses 20 questions from four public research papers. The local model scored 11 fully correct and nine partially correct answers with retrieval. Without retrieval, nine answers were partially correct and 11 incorrect. Of 48 distinct question–passage citations, 15 supported the answer, 25 partially supported it and eight gave no support. These are content judgments by gpt-6-luna at xhigh. The independent page-location check found the reference document and page for 11 questions. Raw outputs, judgments and summaries are in data/eval-lab, data/lab-judgments and data/metrics.

For the related-work check, the app displays catalog records, scans the selected draft for their titles and quotes both sources when a retrieved abstract supports a specific overlap. An empty generated search is retried using topic terms. Exact-title confirmation, possible topical relevance and passage-supported overlap are separate outputs.

    python eval/lab_literature.py
    python eval/lab_replays.py
    python eval/error_analysis.py --run eval-frozen
    python eval/review_citations.py --run eval-frozen

The main review run keeps format failures on record. A supplementary recovery can be started with `python eval/recover_formats.py PAPER METHOD`. It uses the same model with an additional brevity instruction only after two malformed generations. Its output and protocol live in a separate namespace. For an eligible pre-review manuscript, pass `--source eval-early`. The recovery checks the recorded failure against the SHA-256 of the earlier PDF and records that version alongside its output.

    python pipeline/class_packets.py
    python pipeline/class_packets.py --import-labels PATH_TO_ANNOTATED_BATCHES

Whole-corpus classification uses 2,430 input packets covering 48,581 historic review IDs. Preparing a packet does not label its reviews. The importer checks complete coverage of each packet, its hash, gpt-6-luna/xhigh provenance and allowed severity values. Each annotated review includes an explicit issue list, including an empty list where appropriate.


The four-topic related-work evaluation requested 12 external works from each method. The direct model supplied six titles, including one rendering of the input draft. None were confirmed by the title lookup. Scholar supplied 12 records, excluding the input drafts after normalization for PDF hyphenation. Eleven were reconfirmed by title search. All 12 identifiers resolved to matching titles in OpenAlex (five preprints, four conference papers, two articles and one dissertation). Identifier resolution establishes the catalog identity. This study did not rate relevance to the proposed research.

The historical archive also contains 12,140 official chair decision notes for 2018–2023. The notes for the 50 evaluation papers are stored separately. The public interface reveals them only after the user opens the published outcome panel.

    python pipeline/decisions.py
    python eval/lab_catalog.py

The stored four-method cohort runs with its original source and annotation snapshots under `.evaluation-runtime/baseline-v1` and `data/eval-frozen/indexes`. The live manuscript workflow also extracts page-addressable sections, checks setting quotations, conditions critique priors on research design and verifies named comparison works against the submission cutoff. Outputs from the new live workflow use a separate protocol. The matched-paper illustration in the slide deck reports the frozen experiment.

Historical rejected-paper preprints are stored separately from the public PDF mirrors. There must be an OpenReview–arXiv mapping, an arXiv v1 before October of the submission year, and a normalized title match on the first PDF page. Each admitted file has a recorded SHA256 and version description. The appendix and page locations can differ from the submitted manuscript.

### Input versions in the held-out evaluation

The primary cohort keeps its original 50 submission IDs. Four initially downloaded preprints had different first-page titles. Before any of those four were evaluated, the working PDFs were replaced with three forum-linked mirror copies and one earlier title-matched arXiv revision. The original manifest and copies are in `data/heldout-version-audit/`. A title match establishes manuscript identity. Exact revision equivalence to the first submission is unknown. The creation dates for all 25 accepted PDFs and one rejected PDF are on or after the first archived review. These dates flag possible feedback incorporation, including in camera-ready PDFs reprocessed by OCR.

`pipeline/check_heldout_versions.py` checks page counts, first-page titles, stored SHA256 values and archived reviewer dates. `pipeline/heldout_early.py` finds pre-review inputs for the same submission IDs. Early-version estimates use a separate 30-paper availability sample (6 accepted, 24 rejected). The frozen workflow runs on different bytes wherever an earlier manuscript is available. Each output has a source binding in `data/eval-early/<paper>/<method>.input.json`. Primary judgments can be reused only for byte-identical matching packets with identical model output and validated provenance.

    python eval/early_versions.py
    python eval/early_versions.py --reuse-only
    python eval/metrics.py --run eval-early
    python eval/review_citations.py --run eval-early
    python eval/early_versions.py --reuse-judgments
    python eval/metrics.py --run eval-early

### Programmatic manuscript checks

Pass PDF bytes or a local file path to `reviewarena.api.retrieve_candidates`, `verify`, `run_review` or `run_rebuttal`. Candidate results include the source claim, historical family, similarity, conditional-frequency numerator and denominator, and severity. The final review reuses that retrieval path. Rebuttal results include the source reviewer text, per-point actions, a prioritized experiment checklist and downloadable Markdown. A clarification requires manuscript evidence that answers the concern.

In Manuscript review, **Read claims and experimental settings** opens page-linked passages before the three reviewers run. Claims retain the authors’ wording. The separate limitations panel shows disclosures in the manuscript. The retrieval frequency counts distinct historical reviews in the matching cohort. Several mentions of the same family in one review contribute one count. Running the three reviewers in the same session reuses the reading after checking the PDF hash and all claim and setting passages.

The product skills use the 2025 venue-specific score choices. The frozen study retains its original prompts and numeric scale. The official 2025 guides are linked in each reviewer skill.

For the four-method evaluation, a generic request for more comparisons cannot match a reviewer’s request for a particular baseline. The paired report uses current judgments. When an import revises a saved judgment, the importer archives the previous bytes under `judgment-revisions/<paper>/<method>/<SHA256>.json` within that evaluation directory. Reimporting an unchanged judgment creates no revision. The sensitivity report in each run’s `metrics/judgment-sensitivity.json` records the exact changed matches and the before-and-after counts for identical packets and common papers.

The released taxonomy keeps the original 6luna/xhigh family names and their reviewed member categories. New categories are assigned by the mean of their cosine similarities to the family centroid and its closest reference example. Each row records how its family was assigned. Use `pipeline/taxonomy.py --propose-recluster` to generate a candidate naming packet. Importing a verified set of new names explicitly promotes that reference. Existing frozen indexes retain their original memberships. A source-verified audit can exclude a misleading or unclear example from family retrieval. Its original review remains available through critique-text search. The exclusion follows the specific manuscript quote, reviewer quote and reference family into each immutable snapshot.

The offline taxonomy build also stores the BGE vectors for historical triggers and reviewer text. The passage order, text, encoder implementation, tokenizer and ONNX weights determine the cache key. `python eval/vector_cache.py` compares loaded vectors with fresh encoding on the current index. Its timings cover the vector step only.

Run `python eval/retrieval_families.py` to compare historical trigger and abstract retrieval on the same candidate pool. Each query excludes its own paper and duplicate trigger text. Only source-verified pairs with original reference-family membership enter this diagnostic. It measures recovery of the named family from another manuscript. The 2025 evaluation separately measures recovery of specific published reviewer concerns.

### Tracing recovered concerns to the reviewer inputs

The frozen experiment keeps the original inputs and output of each reviewer. `eval/reviewer_inputs.py` reconstructs each generating reviewer's prompt and verifies it against the cached model response. A 6luna xhigh assessor checks whether a specific historical issue expresses the scientific check shared by the prediction and the published concern. When the generating reviewer received no matching issue, a second packet tests the remaining retrieved candidates. The two decisions stay separate and the assessor receives no verifier dispositions. Corpus shows the results for completed assessments. This diagnostic is conditional on an existing published-concern match.

For the current product workflow, `python eval/product_sample.py` selects two accepted and two rejected held-out papers before the run and pins the historical index and model protocol. `python eval/product_provenance.py` checks each retrieved historical passage against its original PDF, the reviewer quotation against the archived review, and the target claim and accepted evidence against the target PDF. Neither check estimates whether the proposed criticism is scientifically justified.

### Independent human checks

The blind matching sheets for Group 16 are under `data/eval-frozen/human-audit/`. Give each member their own `rater1.html` or `rater2.html` (the original CSVs can also be used). Each standalone form displays the unchanged pair and the verbatim reviewer comment. Open it locally, rate independently, and download the CSV before closing. To resume, import your own partially completed CSV. Return the two completed CSVs to that folder for scoring. Enter 1 when the predicted issue and the published concern identify the same specific problem, or 0 otherwise. Complete the sheets independently. Scoring checks source hashes before computing agreement. Use `python eval/audit.py --run eval-frozen --status` to check completion without revealing decisions. After both raters finish, the agreement output records observed agreement, all four label counts and agreement conditional on each model decision. Each conditional rate includes its denominator. A missing class has an undefined rate, so overall agreement alone cannot validate that class. When both raters use the same single category throughout, Cohen’s κ is undefined and is stored as null.

After the 200 primary slots have a report or a documented JSON-format failure, run `./.venv/bin/python eval/validity_sample.py`. This freezes a seeded sample of 50 generated concerns and verifies the selected manuscript PDFs against the original manifest. In `data/eval-frozen/validity-audit/rater.csv`, judge each concern as `valid`, `invalid` or `insufficient` against the manuscript. Give a reason for every judgment and an evidence page for a valid or invalid concern. Run the same command with `--score` after rating. The summary groups the independent validity ratings by method and by whether a published reviewer raised a matching concern. A missing semantic judgment is tracked separately.

To rate ScholarMate answers or citations against the actual PDF page, run `./.venv/bin/streamlit run eval/lab_rater.py --server.address 127.0.0.1 --server.port 8523`. Each view hides the generating method, shows the cited page, and exports the original CSV schema. Record each decision before moving to the next item and download the file to preserve it. ScholarMate's human assessment sheets are under `data/eval-lab-human/`. Rate the 40 answers as correct, partial, incorrect or missing. For the 48 cited passages, choose supports, partially_supports or does_not_support after reading the associated claims. Give a reason for each decision. The completed human summaries and the existing model-judged results are stored separately.

    python eval/audit.py --run eval-frozen --score
    python eval/lab_human.py --score

### Check a reviewer's requested comparisons

In **Rebuttal**, upload the manuscript, enter the reviewer's comment and select **Check works mentioned by the reviewer**. Each verified title opens its dated publication record. Bibliography matches and comparison-table captions are shown separately with PDF page highlights. Check the comparison settings and manuscript version before drafting a response.

In **Corpus**, open **Historical reviewer request · ConViT and CoAtNet** for a public example. Regenerate its official arXiv records with `./.venv/bin/python pipeline/publication_record.py 2103.10697 2106.04803`, then reproduce the source check with `./.venv/bin/python eval/comparison_demo.py`.

In a manuscript review, open **Open questions for the authors** to see unresolved checks anchored to the current draft. Enter a page, an experiment or a revision decision, select **Prepare author notes**, and download the notes for the next meeting. These questions are excluded from verified weaknesses and acceptance statistics.

### Check claim coverage in retrieval

Run `./.venv/bin/python eval/claim_coverage.py` to compare maximum-score assignment with assignment covering the available manuscript claims. The diagnostic reads the held-out PDFs and uses the same 20 historical critique families in both conditions for each manuscript. It reports how many claims have a candidate, which assignments changed and the retrieval score difference. Individual historical examples within a family can differ. The full review evaluation measures recovery of published reviewer concerns separately.

When a verifier partially answers an author question, the revision notes include its exact manuscript quotation and page alongside the triggering claim and the author's own decision. **Find figures and tables for these questions** retrieves up to two printed captions per question. Inspect the rendered pages before recording a decision. The notes identify these captions as suggestions. Run `python eval/figure_evidence.py` to reproduce the held-out caption provenance check and the page 6 Switch SAE retrieval example.

### Weekly meeting records

For a weekly brief, select the notes or other records documenting the group's own work. Completed activities are quoted from those records. With no meeting records selected, research papers supply the material for a literature discussion. Download the brief to retain its source passages, or record an agreed decision in the local library for the next meeting. The public example uses observed results from the project's 20-question evaluation. Rebuild it with `./.venv/bin/python eval/lab_weekly.py`.

In **Open questions for the authors**, select **Compare question wording with historical reviews** to see the exact reviewer quotation and the historical question used for retrieval. The rank compares each proposed question with the same manuscript’s retrieved candidate checks. A low rank signals a possible change in the scientific question. The downloaded notes preserve the source and rank.
