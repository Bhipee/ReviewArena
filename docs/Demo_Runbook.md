# Group 16 live demonstration

Use two terminal windows for the local model and Streamlit. Before class, open the manuscript and rebuttal workspaces and confirm the example PDF and the replay are available. Use an author-owned or public manuscript. Open **ForDemo** and choose the ICLR 2025 Switch Sparse Autoencoders example and the 1 October 2024 literature cutoff.

| Time | Operator | Audience sees |
|---|---|---|
| 0:00–0:25 | YANG Yifan introduces Switch Sparse Autoencoders. HOU opens the manuscript. | Ask the audience whether “better reconstruction” holds when compute is fixed and when model width is fixed. |
| 0:25–1:10 | HOU selects **Run three reviewers**. YANG Botao explains the historical evidence while the review starts. | Show one progress event. Explain how a prior reviewer’s question and its original manuscript passage enter retrieval. At 1:10 switch to **ForDemo → Load saved review** for the prepared case. |
| 1:10–2:35 | HOU opens the two author questions and selects **Find figures and tables for these questions**. LIU Zheng interprets Figure 3 on page 6. | Read the caption. Switch beats TopK at matched compute in the left panel. At matched width it performs slightly worse in the right panel. The author has a concrete reason to qualify the sentence. |
| 2:35–3:20 | HOU records the qualification and downloads the author notes. | Open the downloaded file. Point to the manuscript title, version fingerprint, Figure 3 caption and the author’s decision. The note can travel back to the coauthors with its evidence. |
| 3:20–4:25 | HOU opens **Rebuttal** for the same paper, selects **Use an actual reviewer comment** in **ForDemo** and clicks **Load saved rebuttal draft**. | Show the reviewer’s question about overlap among experts’ sparsity patterns. Download the response with the overlap measurement still listed as proposed work. |
| 4:25–5:00 | YANG Yifan closes with the paired evaluation. | Give the number of fully judged manuscripts from slide 7. Distinguish a useful revision question from a demonstrated weakness. Explain why public manuscript revisions complicate comparison with the original review. |

For a live revision decision, choose **ForDemo → Load saved review**. Open **Open questions for the authors**, click **Find figures and tables for these questions**, and open **Figure 3 · p. 6** under the question about the sparsity frontier. The left panel compares equal compute, where Switch beats TopK. The right panel compares equal width, where Switch performs slightly worse than TopK. Enter “Qualify the claim by training compute and point readers to Figure 3, left” under that question. Prepare and download the notes. They preserve the author’s decision alongside the complete printed caption. The question comes from a saved review; caption retrieval, page rendering, and the download run live. Use this sequence within the manuscript-review slot.

For the author and supervisor meeting, choose **ForDemo → Load saved review**. Open **Open questions for the authors**. Type the decision to check the training budgets in the experimental setup, select **Prepare author notes**, then download the Markdown. The note includes the actual claim on page 1 and its historical reviewer link.

For the Switch SAE example, choose **ForDemo → Load saved manuscript reading** to open its verified passages immediately. Show the same-compute comparison on page 2, then the fixed-parameter limitation on page 10. **Read claims and experimental settings** performs a fresh reading for an uploaded draft.

## Suggested implementation ownership

| Member | Ownership | Live role |
|---|---|---|
| YANG Botao | Historical OpenReview data, PDF matching and labeling quality | Explain data split and provenance |
| LIU Zheng | Trigger retrieval, ranking, verifier and evidence checks | Explain one accepted or dismissed concern |
| HOU Zhitian | Agent workflows, app integration and playback | Operate the live UI |
| YANG Yifan | Evaluation, supporting slides and timing | Introduce the scientific question and close |

The membership assignments are proposed for this demo. The course grades the group collectively. Cite a measured result only when its output and denominator are visible in the prepared checkout.

### Independent ratings before class

Two group members each open their own offline form and assess the same 100 pairs independently. Select **Same issue** when the prediction identifies the specific problem raised in the quoted review. Download the CSV when finished, or import your own partial CSV to resume.

- [Open the first rater’s form](../data/eval-frozen/human-audit/rater1.html)
- [Open the second rater’s form](../data/eval-frozen/human-audit/rater2.html)

Return each downloaded file under its original name to `data/eval-frozen/human-audit/`. From the project root, run `./.venv/bin/python eval/audit.py --run eval-frozen --status` to check both counts. Once both reach 100, use `--score` in place of `--status` to calculate agreement.

The matching audit froze 100 prediction–reference pairs from five manuscripts. Direct review contributed 29 pairs, whole-paper retrieval 29 and trigger retrieval 42. Report agreement with those denominators. The separate 50-concern validity audit asks a different question: can an author substantiate the criticism from the manuscript, including issues the published reviewers missed?

The separate ScholarMate assessment covers 40 answers and 48 cited passages. On the demo computer, use the [local answer and citation rating interface](http://127.0.0.1:8523). The [project README](../README.md) provides its launch command and the CSV return location.

### If asked who generated and who assessed the reviews

The demo uses one local 4-bit Qwen2.5-3B-Instruct model. It takes three roles: theory and assumptions, experiments and evaluation, and clarity and reproducibility. When the verifier passes a concern, the assigned role reviews it. The same model can then summarize the reports as area chair. A separate gpt-6-luna model at xhigh judges whether a generated concern matches a specific concern in the published review. Human agreement is measured separately after the two group members return their ratings.

### If asked what the area chair’s acceptance figure means

The live system uses the verified concerns to look up historical papers that share at least one critique family and severity level. Each matching paper counts once. The denominator includes papers with a main-track acceptance or rejection. For example, an invitation to a workshop track is outside that denominator. The displayed fraction describes this historical group. Estimating the submission’s own chance of acceptance would require calibration. When no concern survives verification, the demo displays no estimate.

### If asked which index the evaluation tested

Slide 2 counts the live retrieval index. For the 50-manuscript experiment, the team froze 57 passage–critique pairs from 44 historical papers so each manuscript would be tested with the same retrieval data. Slides 6 and 7 report that frozen experiment. Measuring the effect of the expanded index requires running the same comparison with the expanded index.

### If asked whether a historical question can transfer across fields

In **Corpus → Which published concerns did the four review methods recover?**, select *MPC-Minimized Secure LLM Inference* under **Inspect a matched review concern**. Its actual reviewer questioned the fairness of comparing a GPU implementation with CPU-only baselines. The experiments reviewer in the trigger-only system raised a broader concern about hardware and implementation quality. Its input included a review of a neuroevolution paper that questioned comparisons under a fixed time budget across different hardware. The two research topics differ, but the fairness check applies to both. The verified method marked this candidate unsubstantiated. Use this case to show which concern reached the reviewer and how the two methods handled it.

[MARILL reviewer-input record](../data/eval-frozen/reviewer-input-audit/inputs/beAlX6RjsW-6-10-0.json) · [Historical reviewer comment](https://openreview.net/forum?id=6BHlZgyPOZY&noteId=ZANbP3kl5h2)

### If asked how the verifier can miss a real reviewer concern

Open *Can Editing LLMs Inject Harm?* and inspect the trigger-only prediction about model scale. Its experiments reviewer received a historical request to test larger models. Two published review entries for the target paper also ask about larger models. The verified workflow stopped at the first check because the retrieved passage gave no direct measurement across scales. Open page 19 of the target PDF to inspect the authors’ list of evaluated models. An author can use that list to discuss the scope of the results. What would happen at larger scales remains an empirical question.

[Reviewer input and first reference](../data/eval-frozen/reviewer-input-audit/inputs/mlCRJnETWz-3-8-0.json) · [Second reference](../data/eval-frozen/reviewer-input-audit/inputs/mlCRJnETWz-3-23-0.json) · [Verifier decisions](../data/eval-frozen/verifier-traces/mlCRJnETWz/D.json) · [Evaluated manuscript, page 19](../data/iclr2025/mlCRJnETWz.pdf#page=19)

### If asked when a historical example misleads the reviewer

The held-out G-Transformer paper estimates treatment outcomes over time. Its trigger-only report questions whether the improvement depends on mT5. One of the retrieved historical comments actually discusses mT5 in a *different* language-model paper. A literal search of the evaluated G-Transformer PDF found no “mT5” on any of its 19 pages. The trigger-only report returned 14 predictions, and the semantic judge matched none to the 19 annotated reviewer concerns. In class, show the target prediction alongside the historical comment. This case illustrates how a detail from an earlier paper can reappear in a question about the new manuscript.

[Target manuscript](../data/iclr2025/XUJcsLvpaQ.pdf) · [Predictions and reference concerns](../data/eval-frozen/judge-input/XUJcsLvpaQ/C.json) · [Historical reviewer comment](https://openreview.net/forum?id=wCFB37bzud4&noteId=QPyHj5xWBc)

In **Manuscript review**, open a retrieved concern and select **Read the surrounding review text**. The panel displays the original review field that contains the quotation. This helps when a short phrase such as “small benchmark suites” leaves out what was small. For example, a symbolic regression reviewer specifies that two tests used 54 and eight equations. A request to extract rules from a single very large knowledge graph asks a different scaling question. Check the unit being scaled before interpreting the match.

### If asked why we retrieve the passage

“We tested 203 queries from 182 historical manuscripts. We excluded the source paper and duplicate trigger text. For each remaining critique family, we took its best matching passage and ranked the families. Using trigger passages, the correct family ranked in the top five in about 52% of queries. With abstracts, it was about 43%. This measures whether we retrieve the right type of concern. The main experiment checks whether we recover a specific published criticism.”

For an error example, open **Corpus → How reliably do the critique families transfer?** and select **misleading · linear-evaluation protocol and performance**. The reviewer described weak performance, while the assigned family implied an unfair comparison. The original review link lets the audience check that distinction.

### If asked which rebuttal strategy works best

In **Rebuttal**, expand **Manuscript evidence and previous responses**. Each strategy has a count of distinct author replies and a count of linked reviewer concerns. A single reply may address multiple concerns. A recorded outcome requires reviewer wording in the archive. Read that wording before interpreting an issue as resolved. A zero count of documented outcomes leaves the success rate unknown.

### If asked what a missing score means

Open **Corpus → Held-out review evaluation**. The first score table averages the scores each simulated panel actually returned. The next table counts papers scored by zero, one, two or three reviewers and gives the correlation for complete three-reviewer panels. A panel that fully abstained contributes no numerical score. Use the total number of estimates and the number accepted to check that both decision classes are represented before discussing AUC.

To explain the two fractions on slide 7, open a matched example in Corpus. If two predictions both identify the same reviewer concern, precision counts two matched predictions and recall counts one recovered reference entry. Conversely, one prediction can address two separately annotated reviewer comments. For example, one review of POCT74JhAl asks for real application data in general and names CIFAR-10 in a separate entry. The same prediction matches both. Recall therefore measures coverage of annotated entries, which can overlap in scientific meaning.

In **Corpus**, select **Inspect a matched prediction and the original review**, then choose the trigger-retrieval example for the quantum scheduling paper. The panel shows the prediction, the citation supplied by the simulated reviewer, the linked historical source and the published reviewer’s wording. **Download the evaluated manuscript** saves the PDF version used by the experiment.

A partial match can also carry an unsupported detail. In *Dynamic Inhomogeneous Quantum Resource Scheduling with Reinforcement Learning*, the published reviewer asked for comparisons of training time. The trigger-only prediction raised experimental time cost and also gave an O(n⁴) complexity claim. Its citation field reproduces a historical reviewer’s comment about *Robust Graph Dictionary Learning*. The semantic match captures the shared timing concern. Establishing a complexity bound for the quantum scheduling algorithm requires separate evidence from the target manuscript.

[Generated concern and target review](../data/eval-frozen/judge-input/8WtBrv2k2b/C.json) · [Historical graph-learning review](https://openreview.net/forum?id=qxRscesArBZ&noteId=yKkvTC-zCS)

Slide 7 compares papers for which all four original methods produced a scored report. To answer how many published issues a user would actually receive across all finished attempts, open the delivery-recall table in Corpus. Its denominator includes manuscripts with a recorded generation failure. A failed attempt delivered zero issues. Count failures by report attempt, since two methods can fail on the same paper.

### If asked whether the reviews invented papers

Open **Corpus → Did the reviewers request comparisons to identifiable papers?** This counts specific works named in missing-comparison requests in the generated reports. If no report names a work, the denominator is zero and citation authenticity cannot be estimated from those reports. The ConViT and CoAtNet example comes from a published reviewer’s request and demonstrates the lookup separately.

The citation panel opens on the manuscripts assessed for both direct and verified review. Give the number of reports requesting a named comparison first, then the number of named works confirmed before the cutoff. If a method requested no named comparisons, its confirmation rate is undefined. This panel requires citation assessments for A and D only, so it can include manuscripts outside the four-method cohort on slide 7.

The direct review of *Accelerating 3D Molecule Generation via Jointly Geometric Optimal Transport* names EDM, GeoLDM and EquiFM in a request for a computational-cost comparison. Select **Show named comparisons and catalog records** to inspect the generated sentence and all three works. Select **Inspect the evaluated PDF** and enter page 8. Table 2 already compares sampling steps and S-Time on GEOM-DRUG for every named method and for GOAT. Ask which aspect of computational cost the student would still need to address. A valid publication link establishes that a work exists. The table is the evidence for deciding what comparison was supplied.

### If asked whether retrieval examines every claim

In the 50-paper coverage check, each paper contributed three attributable manuscript statements. Assigning each historical family to its highest-scoring statement covered 128 of the 150 statements. Keeping the same 20 families per paper and assigning one to each eligible statement where possible covered all 150. This tests which statements receive a question candidate. The separate, blinded four-method evaluation measures recovery of published reviewer concerns. The per-paper evidence is in `data/metrics/claim-coverage.json`.

### If asked how the system behaves on rejected papers

In **Corpus → Which published concerns did the four review methods recover?**, switch **Published decision** from **All** to **Rejected**. Read the number of fully judged papers before reporting results. The table and matched examples both use that selected group. Switch to **Accepted** to inspect its denominator and recovered concerns separately. Manuscript timing can also differ between these groups.

### If asked whether changing the manuscript version changes the review

Open **Corpus → Manuscript versions in the held-out review experiment**. The second table compares different PDFs for the same paper under the same method. One example is *Poisson-Dirac Neural Networks for Modeling Coupled Dynamical Systems across Domains*. Direct review gave both PDFs a mean score of 7. On the pre-review PDF, it raised the need for more background on Dirac structures, matching a published request for more background on differential geometry. The primary PDF's generated review had no matching prediction for that concern. This comparison shows how two review outputs differ. It cannot identify which change in the manuscript caused the difference.

### If asked whether the tested manuscript matches the reviewer's copy

In the Switch SAE replay, select **Reveal actual reviews and decision → Did the model-scale evidence change after review?** The 10 October 2024 public preprint describes GPT-2 Small on page 5. The 2 November reviewer questions the experimental scale. The later public copy reports an experiment on one Gemma 2 2B layer on page 7 and gives results on page 15. Toggle between the three original pages. This comparison shows how the documented evidence expanded. The authors' reason for adding the experiment and the exact file the reviewer received are unknown.

### If asked whether an adapted question still reflects its source

Open **Corpus → Do adapted questions preserve the original reviewer’s concern?** Counting source citations and judging whether a question preserves the reviewer’s scientific test measure different things. In four manuscripts, 80 retrieval links were traceable. ReviewArena proposed eight questions. Independent 6luna xhigh assessments found one that both preserved the scientific check and had a premise supported by the target claim. In the manuscript workspace, **Compare question wording with historical reviews** displays the original quotation so that a supervisor can inspect the connection.

## Browser replay backup

The backup in `demo/ReviewArena_replay.mp4` runs 00:01:07.56. Follow the same Switch SAE manuscript from its claim and Figure 3 to the exported revision notes and rebuttal. The recording also shows the later Gemma experiment and score reveal. Both downloads were checked during recording.

## Alternate five-minute group-meeting walkthrough

| Time | Live action | Evidence to open |
|---|---|---|
| 0:00–0:40 | HOU opens Lab meeting and selects the four public example PDFs. YANG Yifan introduces a student preparing a weekly meeting. | Show the selected draft and the group documents. |
| 0:40–1:45 | Ask what Auto-CoT automates. Expand one supporting passage and select Show original PDF page. | Read the claim alongside the highlighted passage and its page number. |
| 1:45–2:45 | Select related-work-gap and the Auto-CoT manuscript. Request related papers on chain-of-thought demonstrations. | Open Tool calls and a publication record. Explain what an exact-title match in the manuscript can establish. |
| 2:45–3:35 | Select reviewer-2 and ask what a supervisor should challenge. | Inspect contributions, weaknesses and questions for the author, each with its own passage list. |
| 3:35–4:20 | Open Weekly brief and select the group evaluation record, or inspect the saved public run. Download the Markdown and record a decision for the next meeting. | Show the group evaluation note as the source for the 20 completed questions and the 11 answers citing the reference page. Save a decision to inspect the remaining answers. |
| 4:20–5:00 | Open Corpus → Research-group Q&A evaluation. | Report the 20-question outcome and the eight unsupported passage citations. |

For the Q&A results, the two counts of 11 on the slide refer to different sets. Eight of the 11 answers that cited the reference page were graded fully correct. Three other fully correct answers did not cite that page. Open the reference-page table in the Q&A evaluation to see the overlap.

Use a dated note for claims about progress this week. Papers alone support a discussion of published results. The catalog panel reports what the source returned and whether the title appears in the selected manuscript.

For a reproducible group-meeting example, select **Use the public research-group example**, choose the task, then turn on **Inspect a saved public run**. The interface displays the original question and document names. The source packet and every displayed document are checked by SHA256 before playback. Turn the toggle off to send a new question to the live model.

To take the weekly brief back to the group, open **Record a decision for the next meeting**. Enter the agreed action and select **Save decision to local library**, then **Download meeting notes**. The exported brief includes the confirmed action, the measured result and its cited source. The saved decision is also available in **Saved lab documents** for the next meeting.

The group-meeting backup in `demo/ScholarMate_replay.mp4` runs for 22 seconds. It shows a highlighted manuscript page, three catalog links, the Reviewer #2 sections, the weekly brief and the evaluation panel. Recording also verifies a real Markdown download. Use the live controls for the five-minute demonstration.

On the four-topic catalog check, title search reconfirmed 11 of 12 Scholar records. All 12 identifiers resolved to their recommended titles in OpenAlex. The direct model returned six titles and the same title-check procedure confirmed none. One Scholar record is a dissertation. Explain bibliographic identity separately from research relevance.


## Timing-table exchange

The historical manuscript is *NTK-SAP*. In the original verifier replay the timing table closed the broad runtime question. Select **Inspect the scope-aware verifier** to compare two questions against that same table. It reports CIFAR-10 pruning times of 17 s and 24 s for NTK-SAP and Iterative SNIP. When asked for measured end-to-end training times on the same dataset and methods, it abstains. The source links open the original reviewer comment and author reply.

For the 50-paper frozen experiment, `eval/verifier_trace.py` checks how often the verifier explicitly abstained, returned an unusable verdict or lost an exact page quotation. It uses the original cached model responses and must reproduce the actual saved verdict and evidence for every candidate before emitting a trace. Select **Four-method comparison** to follow the manuscripts shown on slide 7. The first-stage counts track retrieved questions only. To discuss missed published concerns, open the matched-prediction audit and check whether the corresponding historical issue reached the reviewer in the first place. The audit covers a selected subset of matches, so it cannot attribute every missed concern to a particular stage.


For evaluation questions, explain the version audit. All 50 active PDFs match the submission title on page one. The creation dates of the 25 accepted PDFs and one rejected PDF are on or after their first archived review. Feedback may already be reflected in these files. Consequently the primary score-based AUROC also reflects differences in the available manuscript versions. The separate early-version experiment uses only inputs dated before the first archived review.
