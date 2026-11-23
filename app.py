import asyncio,hashlib,json,os,time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue,Empty
from datetime import date
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)

from reviewarena.comparisons import POOL,comparison_counts
from reviewarena.kb import DATA,stats,accepted_decision,current_snapshot,family_ratings,historical_review_section
from reviewarena.paper import parse_pdf,highlight
from reviewarena.workflow import SCORE_LABELS,run_review,rebuttal,inspect_manuscript,chair_recommendation
from reviewarena.claims import declared_limitations
from reviewarena.comparison_reader import inspect_comparison
from reviewarena.workflow import ask
from reviewarena.lab import run_lab,meeting_markdown
from reviewarena.demo_ui import action_buttons,remember_demo
from reviewarena.demos import chair_inputs,demo_path,fingerprint,load_demo,public_lab_result,read_review_demo,read_scope_demo,review_demo_path
from reviewarena.summary_ui import render_summary
from reviewarena.api import experiment_checklist,rebuttal_markdown,author_questions,author_question_notes
from reviewarena.library import document,list_documents,read_documents,save_documents,saved_pdf

st.set_page_config(page_title="ReviewArena",layout="wide")
st.markdown("""<style>div[data-testid="stAppViewContainer"] .block-container{padding-top:2.4rem;max-width:1320px} [data-testid="stSidebar"]{background:#f1f3f1} h1,h2,h3{letter-spacing:-.035em} [data-testid="stMetricValue"]{color:#285b4f}</style>""",unsafe_allow_html=True)
st.title("ReviewArena")
activity=st.sidebar.radio("Workspace",["Manuscript review","Rebuttal","Lab meeting"])
from reviewarena.model import local_endpoint
endpoint=os.getenv('REVIEWARENA_API_URL','http://127.0.0.1:8766/v1')
model_label=os.getenv('REVIEWARENA_MODEL','default_model')
if endpoint.rstrip('/')=='http://127.0.0.1:8766/v1' and model_label=='default_model':
    model_label='Qwen2.5-3B-Instruct'
st.sidebar.caption(('Local model · ' if local_endpoint(endpoint) else 'Online model · ')+model_label)
st.sidebar.caption("For authors and supervisors. Use work you are authorized to process with the configured model.")
def render_text(value):
    if isinstance(value,list):
        for item in value:st.write(item)
    else:st.write(value)

def call(coro):
    try:
        with st.spinner("Reading evidence…"):return asyncio.run(coro)
    except Exception as exc:
        st.error(f"The workflow could not finish. {exc}")
        return None
def manifest(year):
    path=DATA/f'iclr{year}/manifest.json'
    return json.loads(path.read_text()) if path.exists() else []
def show_evidence(content,ev):
    st.markdown(f"**Page {ev['page']}** · {ev.get('reason','')}")
    st.write(ev['quote'])
    st.image(highlight(content,ev['page'],ev['quote']),width=600)
def render_comparisons(content,reading):
    st.caption('Prior work published before '+reading['before'])
    if not reading['works']:st.write('No named work was identified in this reviewer comment.')
    tables={}
    for work in reading['works']:
        st.markdown('**'+work['mention']+'**')
        record=work['catalog_record']
        if record:
            st.link_button(record['title']+' · '+record['published'],record['url'])
        else:st.caption('Catalog identity unresolved for '+work['query'])
        for citation in work['bibliography']:st.write(f"Manuscript p. {citation['page']} · {citation['quote']}")
        for passage in work['comparison_passages']:tables[passage['page'],passage['quote']]=passage
        if not work['comparison_passages']:st.caption('No matching comparison-table caption located in the extracted PDF text.')
    for passage in tables.values():show_evidence(content,{**passage,'reason':'Comparison-table caption in this PDF'})

def render_scope(content,result):
    if any(c.get('page') for c in result.get('claims',[])):
        with st.expander("Claims as stated in the manuscript"):
            for claim in result['claims']:
                if claim.get('page'):show_evidence(content,dict(page=claim['page'],quote=claim['text'],reason=claim.get('claim_type','')))
    if disclosures:=result.get('declared_limitations'):
        with st.expander("Limitations already stated by the authors"):
            for item in disclosures:
                show_evidence(content,{**item,'reason':'Author statement'})
    if result.get('settings'):
        with st.expander("Experimental settings from the manuscript"):
            for setting in result['settings']:
                st.write(setting['kind'].capitalize()+' · '+setting['name'])
                show_evidence(content,setting)

if activity=="Corpus":
    import pandas as pd
    st.header("Historical review corpus")
    snapshot=current_snapshot()
    if POOL.exists():
        coverage=pd.DataFrame(comparison_counts(POOL.stat().st_mtime_ns))
        paper_col,review_col=st.columns(2)
        paper_col.metric("Searchable comparison papers",f"{coverage.papers.sum():,}")
        review_col.metric("Official reviews with indexed excerpts",f"{coverage.reviews.sum():,}")
        with st.expander("Coverage by venue and year",expanded=True):
            st.dataframe(coverage,hide_index=True)
            st.caption("Counts include papers with a usable public review. Conference submission totals also include submissions without a public review.")
            st.caption("NeurIPS 2021–2025 snapshot audit (23 Nov 2026): 17,831 accepted papers and 920 rejected papers. Rejected authors can opt in to publication. This sample overrepresents accepted papers and its acceptance share cannot estimate a submission’s chances.")
            st.link_button("NeurIPS public review policy", "https://neurips.cc/Conferences/2025/CallForPapers")
    with st.expander("ICLR archive for verified critique retrieval, 2018–2023"):
        counts=pd.DataFrame(stats())
        st.bar_chart(counts,x='year',y='official_reviews')
    inventory_file=DATA/'metrics/archive-inventory.json'
    if inventory_file.exists():
        with st.expander("Full source archive, 2018–2025"):
            inventory=json.loads(inventory_file.read_bytes())
            total=inventory['whole_archive']
            st.write(f"{total['papers']:,} submissions and {total['official_reviews']:,} official reviews in the source snapshots.")
            st.dataframe(pd.DataFrame(inventory['by_year']).set_index('year'))
            st.caption("This source inventory predates the expanded Live comparison index. Frozen evaluation uses its own historical split.")
    paired_path=DATA/'eval-frozen/metrics/paired.json'
    if paired_path.exists():
        paired=json.loads(paired_path.read_text())
        if paired.get('papers') and not paired.get('multiple_protocols_within_method'):
            with st.expander("Held-out review evaluation"):
                names={'A':'Direct review','B':'Whole-paper retrieval','C':'Trigger retrieval','D':'Verified review'}
                table=pd.DataFrame([{'Method':names[key],'Predicted issues':row['predictions'],
                    'Matched predictions':row['matched_predictions'],'Recovered reviewer issues':row['matched_references'],
                    'Published reviewer issues':row['references'],'Papers without predictions':row['no_prediction_papers']} for key,row in paired['methods'].items()]).set_index('Method')
                st.write(f"{paired['papers']} of 50 manuscripts have judgments for all four methods.")
                frozen_sources=pd.read_parquet(DATA/'eval-frozen/indexes/critique.parquet',columns=['paper_id'])
                st.caption(f"The two trigger-retrieval methods in this experiment used a fixed index of {len(frozen_sources):,} passage–critique pairs from {frozen_sources.paper_id.nunique():,} historical papers.")
                st.bar_chart(table[['Recovered reviewer issues']],horizontal=True)
                st.dataframe(table)
                st.caption("Each count uses the same manuscripts. All published concerns count toward recall, including those on papers where a method raised no concerns.")
                if all('score_pairs' in row for row in paired['methods'].values()):
                    st.write("Reviewer scores and decisions")
                    scores=pd.DataFrame([{'Method':names[key],'Scored papers':row['score_pairs'],
                        'Score correlation (Spearman)':row['spearman'],'Papers with an acceptance estimate':row['decision_pairs'],
                        'Accepted among estimates':row['accepted_decision_pairs'],'Acceptance AUC':row['auc']}
                        for key,row in paired['methods'].items()]).set_index('Method')
                    st.dataframe(scores)
                    st.caption("Spearman compares predicted and published mean scores. Acceptance AUC uses the historical acceptance estimate and needs both decisions. Blank cells indicate an undefined metric.")
                if all('scoring_panel_counts' in row for row in paired['methods'].values()):
                    st.write("How many of the three reviewers gave a score?")
                    st.table([{'Method':names[m],**{f'{n} scored':row['scoring_panel_counts'][str(n)] for n in range(4)},
                               'Full-panel Spearman':row['complete_panel_spearman']}
                              for m,row in paired['methods'].items()])
                    st.caption("The main correlation uses the mean of available reviewer scores. The full-panel correlation uses only papers scored by all three reviewers. A blank correlation means the available scores cannot establish a rank correlation.")
    citation_results=DATA/'eval-frozen/metrics/citation-confirmation.json'
    if citation_results.exists():
        citations=json.loads(citation_results.read_bytes())
        if all('lookup_error' in row for row in citations.values()):
            with st.expander("Did the reviewers request comparisons to identifiable papers?"):
                paired_only=False
                if all('same_manuscripts' in row for row in citations.values()):
                    paired_only=st.radio("Citation assessment sample",["Manuscripts assessed for both methods","All assessed reports"],horizontal=True)=="Manuscripts assessed for both methods"
                for method,label in [('A','Direct review'),('D','Verified review')]:
                    row=citations[method]['same_manuscripts'] if paired_only else citations[method]
                    st.write(f"{label}: {row['reports_with_named_comparisons']} of {row['labeled_reports']} assessed manuscript reports requested a comparison to a named work.")
                    if row['named_comparisons']:
                        rate=row['confirmation_rate']
                        st.caption(f"Confirmation among completed lookups: {rate:.1%}" if rate is not None else "All lookups failed. The confirmation rate is undefined.")
                        st.caption(f"Confirmed before cutoff: {row['confirmed']} · No matching record: {row['unconfirmed']} · Lookup error: {row['lookup_error']}")
                    else:
                        st.caption("No titles to check. The confirmation rate is undefined.")
                if any(row['named_comparisons'] for row in citations.values()) and st.checkbox("Show named comparisons and catalog records"):
                    files=sorted((DATA/'eval-frozen/citation-audit').glob('*/[AD].json'))
                    for file in files:
                        other='D' if file.stem=='A' else 'A'
                        if 'assessed_paper_ids' in citations[file.stem] and file.parent.name not in citations[file.stem]['assessed_paper_ids']:continue
                        if paired_only and file.parent.name not in citations[other].get('assessed_paper_ids',[]):continue
                        audit=json.loads(file.read_bytes())
                        if not audit['comparisons']:
                            continue
                        method='Direct review' if file.stem=='A' else 'Verified review'
                        st.caption(f"{method} · {file.parent.name}")
                        for quote in dict.fromkeys(r['quote'] for r in audit['comparisons']):
                            st.write(quote)
                            for match in (r for r in audit['comparisons'] if r['quote']==quote):
                                if record:=match.get('catalog_record'):
                                    st.markdown('['+record['title']+']('+record['url']+')')
                                else:
                                    st.write(match['title'],match.get('catalog_status','unconfirmed'))
                        st.markdown('[Public manuscript and reviews](https://openreview.net/forum?id='+file.parent.name+')')
                        if st.checkbox("Inspect the evaluated PDF",key=f'citation-pdf-{file.parent.name}-{file.stem}'):
                            import pymupdf
                            with pymupdf.open(DATA/'iclr2025'/(file.parent.name+'.pdf')) as doc:
                                page=st.number_input("Page",min_value=1,max_value=len(doc),value=1,key=f'citation-page-{file.parent.name}-{file.stem}')
                                st.image(doc[page-1].get_pixmap(matrix=pymupdf.Matrix(1.4,1.4)).tobytes('png'),width=720)
                st.caption("Repeated mentions of the same catalog query count once per manuscript and method. The literature cutoff is 1 October 2024.")
    trace_path=DATA/'eval-frozen/metrics/verifier-traces.json'
    if trace_path.exists():
        trace=json.loads(trace_path.read_bytes())
        if trace.get('first_verdicts'):
            with st.expander("How did the manuscript verifier decide?"):
                if trace.get('paired',{}).get('papers'):
                    cohort=st.radio("Manuscripts to inspect",["Four-method comparison","All traced manuscripts"],horizontal=True)
                    if cohort=="Four-method comparison":
                        trace=trace['paired']
                st.write(f"The recorded model responses cover {trace['candidates']} historical questions across {len(trace['papers'])} held-out manuscripts.")
                labels={'unsubstantiated':'Insufficient evidence','addressed':'Paper answers the question','valid':'Supported concern'}
                decisions=[{'Decision':label,'Initial model response':trace['first_verdicts'].get(key,0),
                            'After evidence checks':trace['final'].get(key,0)} for key,label in labels.items()]
                unrecognized=sum(n for key,n in trace['first_verdicts'].items() if key not in labels)
                if unrecognized:
                    decisions.append({'Decision':'Unrecognized verdict','Initial model response':unrecognized,'After evidence checks':0})
                st.table(decisions)
                st.caption("These counts follow retrieved candidates. Published reviewer concerns can also be missed before verification if retrieval supplies no corresponding candidate.")
                missing=trace['unbound_quotes']
                if missing:
                    found=sum(bool(row['exact_pages']) for row in missing)
                    st.caption(f"{len(missing)} proposed quotations were missing from the retrieved passages. A literal search across all pages of the corresponding manuscripts located {found} of them.")
                st.caption("The four-method cohort includes manuscripts with judgments for every method. All traced manuscripts includes every completed verifier trace.")
    diagnostic_path=DATA/'metrics/retrieval-family-diagnostic.json'
    assessment_path=DATA/'metrics/family-assignment-audit.json'
    if diagnostic_path.exists() and assessment_path.exists():
        with st.expander("How reliably do the critique families transfer?"):
            diagnostic=json.loads(diagnostic_path.read_bytes())
            st.write(f"The table shows how often the recorded critique family ranked first or among the top five families across {diagnostic['eligible_queries']} eligible queries from {diagnostic['unique_query_papers']} historical manuscripts.")
            st.dataframe(pd.DataFrame([{'Retrieval':name,'Top 1':v['top1'],'Top 5':v['top5']} for name,v in diagnostic['methods'].items()]).set_index('Retrieval').style.format('{:.1%}'))
            st.caption("Each family receives the score of its best remaining example. The query manuscript and duplicate trigger text are excluded. Tied ranks share credit.")
            assessment=json.loads(assessment_path.read_bytes())
            audit_counts=assessment['counts']
            st.write(f"A separate gpt-6-luna (xhigh) pass checked {assessment['sample_size']} of {assessment['eligible_detailed_categories']} new, source-linked categories. {audit_counts.get('fits',0)} fit their assigned family, {audit_counts.get('misleading',0)} were misleading, and {audit_counts.get('unclear',0)} were unclear.")
            audit_folder=DATA/'family-audit'/assessment['snapshot']
            cases=json.loads((audit_folder/'packet.json').read_bytes())['items']
            ratings=json.loads((audit_folder/'judgment.json').read_bytes())['ratings']
            choice=st.selectbox('Inspected family assignment',ratings,format_func=lambda r:r['verdict']+' · '+cases[r['i']]['category'])
            case=cases[choice['i']]
            st.write('Assigned family · '+case['family'])
            current_rating=family_ratings(snapshot).get((case['paper_id'],case['review_id'],case['category'],case['review_quote'],case['manuscript_quote']))
            if current_rating and current_rating['verdict']!='fits':
                st.caption('Excluded from examples for this family. The historical review remains searchable by its text.')
            st.write(choice['quote'])
            st.caption(choice['reason'])
            st.link_button('Open this historical review',f"https://openreview.net/forum?id={case['paper_id']}&noteId={case['review_id']}")
    comparison_path=DATA/'metrics/reviewer-comparison-demo.json'
    if comparison_path.exists():
        with st.expander("Historical reviewer request · ConViT and CoAtNet"):
            example=json.loads(comparison_path.read_bytes())
            reading=example['result']
            pdf=(DATA/'iclr2023'/(example['paper_id']+'.pdf')).read_bytes()
            if hashlib.sha256(pdf).hexdigest()==reading['manuscript_sha256']:
                st.write(example['title'])
                st.write(reading['reviewer_comment'])
                st.link_button('Original request for comparisons',example['historical_review'])
                st.caption('The available public PDF includes a comparison. The archived reviewer requested these comparisons. The exact PDF version they reviewed is unknown.')
                render_comparisons(pdf,reading)
    audit_file=DATA/'metrics/historical-source-audit.json'
    coverage_file=DATA/'metrics/label-coverage.json'
    audit=json.loads(audit_file.read_bytes()) if audit_file.exists() else {}
    if audit and coverage_file.exists():
        coverage=json.loads(coverage_file.read_text())
        with st.expander("How much of the archive has been labeled?"):
            if coverage.get('family_reference_sha256'):
                st.write(f"{coverage['named_clusters']} families have reviewed names. The reference defines {coverage['reference_categories']:,} categories. Embedding similarity assigned {coverage['inferred_categories']:,} additional categories.")
            st.write(f"{audit['packets']:,} of {audit['historical_pdfs']:,} archived historical PDFs have a source-verified packet with manuscript pages and review text.")
            st.write(f"Detailed annotation has processed {coverage['pdf_packets_processed']:,} packets. {coverage['papers_with_verified_pairs']:,} manuscripts contributed {coverage['verified_pairs']:,} verified trigger–critique pairs to the index.")
            st.write(f"The separate whole-corpus classification pass has processed {coverage['whole_corpus_reviews_processed']:,} of {counts.official_reviews.sum():,} official reviews.")
    if (DATA/'chair_decisions.parquet').exists():
        import pyarrow.parquet as pq
        st.caption(f"{pq.read_metadata(DATA/'chair_decisions.parquet').num_rows:,} official chair decision notes archived for 2018–2023.")
    if (snapshot/'critique.parquet').exists():
        labels=pd.read_parquet(snapshot/'critique.parquet');st.caption(f"{len(labels)} verified trigger–critique pairs in the retrieval index")
        with st.expander("Which years supply the page-linked review evidence?"):
            by_year=labels.groupby('year').agg(linked_papers=('paper_id','nunique'),linked_reviews=('review_id','nunique'),verified_pairs=('review_id','size'))
            coverage_by_year=counts.set_index('year').join(by_year).fillna(0).astype(int)
            if verified:=audit.get('verified_by_year'):
                coverage_by_year.insert(2,'PDFs available for annotation',[verified.get(str(year),0) for year in coverage_by_year.index])
            st.dataframe(coverage_by_year.rename(columns={'papers':'Archived papers','official_reviews':'Official reviews',
                'linked_papers':'Papers with linked passages','linked_reviews':'Reviews with linked passages','verified_pairs':'Verified pairs'}))
            st.caption("One review can raise several concerns. The distribution of indexed passages determines which years supply examples during retrieval.")
        st.bar_chart(labels.category.value_counts())
        if (snapshot/'taxonomy.parquet').exists():
            taxonomy=pd.read_parquet(snapshot/'taxonomy.parquet')
            families=taxonomy.drop_duplicates(['paper_id','family']).copy()
            families['accepted']=families.decision.map(accepted_decision)
            eligible=families.dropna(subset=['accepted'])
            groups=eligible.groupby('family').agg(papers=('paper_id','count'),accepted_fraction=('accepted','mean'))
            st.caption(f"{families.paper_id.nunique()} labeled papers across {families.family.nunique()} critique families. Acceptance fractions use papers with an explicit acceptance or rejection.")
            with st.expander("Acceptance among labeled papers by critique family"):st.dataframe(groups)
            with st.expander("Which concerns appeared under comparable conditions?"):
                subset=taxonomy
                for field,label in [('year','Publication year'),('paper_type','Paper type'),('claim_type','Claim type'),('decision','Decision')]:
                    choices=sorted(taxonomy[field].dropna().unique().tolist(),key=str)
                    selected=st.multiselect(label,choices)
                    if selected:subset=subset[subset[field].isin(selected)]
                cohort=subset.paper_id.nunique()
                st.caption(f"{cohort} labeled papers match the filters. A paper can have more than one critique family.")
                if cohort:
                    frequency=subset.groupby('family').paper_id.nunique().sort_values(ascending=False).rename('Papers').to_frame()
                    frequency['Share of cohort']=frequency.Papers/cohort
                    st.dataframe(frequency)
        st.dataframe(labels[['category','severity','decision','year','source']],hide_index=True)
    case_file=DATA/'metrics/verifier-response-evidence.json'
    if case_file.exists():
        with st.expander("Historical reviewer exchange · pruning time"):
            case=json.loads(case_file.read_text())
            scope_case=DATA/'metrics/verifier-response-evidence-current.json'
            updated=scope_case.exists() and st.checkbox("Inspect the scope-aware verifier")
            if updated:
                case=json.loads(scope_case.read_text())
            st.caption(f"Selected excerpt from manuscript page {case['manuscript_page']}")
            st.write(case['source_text'][0])
            with_table=st.toggle("Include the author's published timing table")
            variant='excerpt_and_author_response' if with_table else 'manuscript_excerpt'
            if updated and with_table:
                choices={"Original review question":"excerpt_and_author_response","Pruning time on CIFAR-10":"pruning_only_with_table","End-to-end training on CIFAR-10":"matched_end_to_end_with_table"}
                available=[label for label,condition in choices.items() if condition in case['conditions']]
                variant=choices[st.radio("Question to verify",available,horizontal=True)]
            answer=case['conditions'][variant]
            st.write(answer.get('question') or case['question'])
            st.write("Saved verifier decision · "+answer['status'])
            st.write(answer['reason'])
            if with_table:
                st.text(case['source_text'][1].replace('||','|\n|')[:1800])
                st.caption("On CIFAR-10 the published table reports 17 s for NTK-SAP pruning and 24 s for Iterative SNIP. End-to-end training cost requires a separate measurement.")
                if updated and answer['evidence']:
                    st.write("Verifier’s cited text")
                    st.write(answer['evidence'][0]['quote'])
            st.link_button("Original reviewer comment",f"https://openreview.net/forum?id={case['paper']}&noteId={case['review']}")
            st.link_button("Published author reply",f"https://openreview.net/forum?id={case['paper']}&noteId={case['reply']}")
    result_path=DATA/'metrics/lab-correctness.json'
    if result_path.exists():
        with st.expander("Research-group Q&A evaluation"):
            lab=json.loads(result_path.read_text())
            frame=pd.DataFrame({name:lab[name] for name in ('baseline','rag')}).fillna(0).astype(int)
            st.bar_chart(frame.reindex(['correct','partial','incorrect','missing'],fill_value=0))
            st.caption(f"{lab['questions']} questions across {lab['papers']} public research papers. Each answer was judged by {lab['judge']} at {lab['effort']} reasoning effort.")
            st.table(pd.Series(lab['citations'],name='Cited passages').rename(index={'supports':'Supports the answer','partially_supports':'Partly supports the answer','does_not_support':'Does not support the answer'}))
            if page_grades:=lab.get('answer_grades_by_reference_page'):
                grades=pd.DataFrame.from_dict(page_grades,orient='index').fillna(0).astype(int)
                grades=grades.reindex(index=['cited','not_cited'],columns=['correct','partial','incorrect','missing'],fill_value=0)
                st.markdown("**Retrieval-assisted answers by reference-page citation**")
                st.table(grades.rename(index={'cited':'Cited the reference page','not_cited':'Did not cite the reference page'}))
                st.caption("Each row counts answers. The reference page comes from the question’s answer key. An answer can draw on another page of the paper.")
    literature=DATA/'metrics/lab-literature-v3.json'
    identifiers=DATA/'metrics/lab-catalog-identifiers.json'
    if literature.exists() and identifiers.exists():
        with st.expander("Related-work recommendation evaluation"):
            counts=json.loads(literature.read_text());catalog=json.loads(identifiers.read_text())
            table=pd.DataFrame.from_dict(counts,orient='index')[['requested','returned','catalog_confirmed','target_recommendations']]
            table.columns=['Requested','Returned','Confirmed by title search','Recommendations of the draft itself']
            st.dataframe(table.rename(index={'direct':'Direct model','scholar':'Scholar search'}))
            st.caption(f"Four topics. Of {catalog['records']} Scholar results, {catalog['status'].get('verified',0)} resolved to the same title by identifier in OpenAlex. Topical relevance requires separate assessment.")
    planned=manifest(2025)
    titles={p['id']:p['title'] for p in planned}
    paired_results=DATA/'eval-frozen/metrics/paired.json'
    if paired_results.exists():
        paired=json.loads(paired_results.read_bytes())
        if paired['papers'] and not paired.get('multiple_protocols_within_method'):
            with st.expander("Which published concerns did the four review methods recover?"):
                accepted=sum(accepted_decision(p['decision']) is True for p in planned if p['id'] in paired['paper_ids'])
                rejected=sum(accepted_decision(p['decision']) is False for p in planned if p['id'] in paired['paper_ids'])
                st.write(f"{paired['papers']} of {len(planned)} manuscripts have judgments for all four methods. "
                         f"This subset contains {accepted} accepted and {rejected} rejected papers.")
                selected_cohort=paired
                if paired.get('by_decision'):
                    decision_group=st.radio("Published decision",['All','Accepted','Rejected'],horizontal=True)
                    if decision_group!='All':
                        selected_cohort=paired['by_decision'][decision_group]
                        st.caption(f"{selected_cohort['papers']} of {selected_cohort['eligible']} {decision_group.lower()} papers have four judged reports.")
                names={'A':'Direct review','B':'Whole-paper retrieval','C':'Trigger retrieval','D':'Verified review'}
                table=[]
                for method,name in names.items():
                    row=selected_cohort['methods'][method]
                    table.append({'Method':name,'Matched predictions':f"{row['matched_predictions']} / {row['predictions']}" if row['predictions'] else 'No predictions',
                                  'Recovered reviewer concerns':f"{row['matched_references']} / {row['references']}",
                                  'Papers without predictions':row['no_prediction_papers']})
                st.table(table)
                st.caption("The first fraction counts matched predictions. The second counts matched entries in the annotated reviews. Each entry counts once. Closely related requests can occupy separate entries, even within one review.")
                examples=DATA/'eval-frozen/metrics/error-analysis.csv'
                if examples.is_file() and st.checkbox("Inspect a matched prediction and the original review"):
                    evidence=pd.read_csv(examples,keep_default_na=False)
                    evidence=evidence[evidence.paper.isin(selected_cohort['paper_ids']) & (evidence.category=='semantic_match')].reset_index(drop=True)
                    if evidence.empty:
                        st.write("There are no matched predictions in this subset.")
                    else:
                        labels=[f"{names[r.method]} · {titles.get(r.paper,r.paper)} · prediction {int(r.prediction_index)+1}, concern {int(r.reference_index)+1}" for r in evidence.itertuples()]
                        choice=st.selectbox("Matched example",range(len(labels)),format_func=labels.__getitem__)
                        item=evidence.iloc[choice]
                        st.markdown("**Generated prediction**")
                        run_folder=DATA/'eval-frozen'
                        report_path=Path(item.paper)/(item.method+'.json')
                        packet=json.loads((run_folder/'judge-input'/report_path).read_bytes())
                        prediction=packet['predicted'][int(item.prediction_index)]
                        if isinstance(prediction,dict) and isinstance(prediction.get('text'),str):
                            st.write(prediction['text'])
                            citation=prediction.get('citation')
                            if isinstance(citation,str) and citation.strip():
                                st.markdown("**Citation supplied by the simulated reviewer**")
                                st.write(citation)
                                report=json.loads((run_folder/report_path).read_bytes())
                                sources={c['source']:c['title'] for entry in report.get('checked',[])
                                         if (c:=entry['candidate'])['critique_text']==citation}
                                for url,title in sources.items():
                                    st.caption("The citation exactly reproduces a retrieved historical reviewer comment.")
                                    st.link_button(title,url,key='prediction-citation-'+url)
                                if sources:
                                    st.caption("Check the target manuscript before applying a technical detail from that earlier review.")
                                    pdf=DATA/'iclr2025'/(item.paper+'.pdf')
                                    st.download_button("Download the evaluated manuscript",pdf.read_bytes(),file_name=pdf.name,mime='application/pdf',on_click='ignore')
                        else:
                            st.write(prediction)
                        st.markdown("**Published reviewer wording**")
                        st.write(item.review_quote)
                        same_report=evidence[(evidence.paper==item.paper)&(evidence.method==item.method)]
                        other_predictions=same_report[(same_report.reference_index==item.reference_index)&(same_report.prediction_index!=item.prediction_index)]
                        other_concerns=same_report[(same_report.prediction_index==item.prediction_index)&(same_report.reference_index!=item.reference_index)]
                        if not other_predictions.empty:
                            st.markdown("**Other predictions matched to this reviewer concern**")
                            for row in other_predictions.itertuples():
                                st.write(f"Prediction {int(row.prediction_index)+1} · {row.prediction}")
                            st.caption("Each matched prediction counts toward precision. This reviewer concern counts once toward recall.")
                        if not other_concerns.empty:
                            st.markdown("**Other reviewer concerns matched to this prediction**")
                            for row in other_concerns.itertuples():
                                st.write(f"Concern {int(row.reference_index)+1} · {row.review_quote}")
                            st.caption("Each distinct reviewer concern counts toward recall. This prediction counts once toward precision.")
                        st.link_button("Open the paper’s public review forum","https://openreview.net/forum?id="+item.paper)
                audit_file=DATA/'eval-frozen/reviewer-input-audit/summary.json'
                if audit_file.exists():
                    traced=json.loads(audit_file.read_bytes())
                    if traced['judged']:
                        st.markdown("**Where did matching trigger-retrieval predictions come from across all decisions?**")
                        st.write(f"Across {traced['papers']} papers, {traced['judged']} prediction–reviewer-concern matches were checked against the historical issues actually shown to the generating reviewer.")
                        assigned=traced['counts'].get('with_corresponding_historical_concern',0)
                        distinct=traced.get('unique_traced_candidates_by_stage')
                        elsewhere=traced['other_reviewer_assignments'].get('found_in_other_assignments',0)
                        missing=traced['other_reviewer_assignments'].get('absent_from_all_twenty',0)
                        st.write(f"{assigned} matches had a corresponding historical issue in the reviewer's input. "
                                 f"For {elsewhere} matches, only another reviewer received a corresponding issue. "
                                 f"For {missing} matches the specific issue was absent from all 20 retrieved candidates.")
                        if distinct is not None:
                            st.write(f"Across {sum(distinct.values())} distinct manuscript–candidate pairs with a verifier trace, the verifier explicitly abstained on {distinct.get('explicit abstention',0)}. Each candidate counts once per manuscript, including when it matches multiple published comments.")
                        st.caption("This diagnostic selects predictions that already matched a published concern. A matching source shows that a concern was available to the reviewer. It does not establish why the model produced its answer.")
                        matched_cases=traced['cases']
                        if matched_cases:
                            selected=st.selectbox("Inspect a matched review concern",range(len(matched_cases)),
                                format_func=lambda i:titles.get(matched_cases[i]['paper'],matched_cases[i]['paper'])+' · '+matched_cases[i]['reviewer_quote'][:90]+' ('+str(i+1)+')')
                            case=matched_cases[selected]
                            st.markdown("**Generated concern from trigger retrieval**")
                            st.write(case['prediction'])
                            st.markdown("**Published reviewer wording on this manuscript**")
                            st.write(case['reviewer_quote'])
                            st.link_button("Open this manuscript’s review forum","https://openreview.net/forum?id="+case['paper'])
                            if not case['historical_sources']:
                                st.write("The generating reviewer received no historical comment identifying this specific concern.")
                                if other:=case.get('other_reviewers'):
                                    st.caption(other['reason'])
                                    for source in other.get('sources',[]):
                                        st.markdown("**Historical comment assigned to a different reviewer**")
                                        st.write(source['quote'])
                                        st.link_button(source['title'],source['url'])
                            for source in case['historical_sources']:
                                st.markdown("**Historical concern shown to the generating reviewer**")
                                st.write(source['quote'])
                                st.link_button(source['title'],source['url'])
                                st.write("Verifier outcome: "+source['verdict'])
                                st.caption("Verifier rationale: "+source['reason'])
    product_audit=DATA/'eval-product-heldout-four/source-audit.json'
    fit_audit=DATA/'eval-product-heldout-four/question-fit/summary.json'
    if product_audit.exists() and fit_audit.exists():
        with st.expander("Do adapted questions preserve the original reviewer’s concern?"):
            provenance=json.loads(product_audit.read_bytes())
            fit=json.loads(fit_audit.read_bytes())
            totals=provenance['counts']
            st.write(f"On {len(provenance['papers'])} independently selected manuscripts, {totals['retrieved_links']} historical links were verified against the source PDFs and reviews. The current workflow proposed {totals['transferred_questions']} manuscript questions.")
            applicable=sum(row['applicable'] for row in fit['items'])
            st.write(f"Independent 6luna xhigh assessments found that {applicable} of {fit['judged']} questions preserved the historical scientific check and had a premise supported by the new manuscript.")
            st.table([{'Manuscripts':'First three · development' if group=='development' else 'Fourth · held out',
                       'Ranked first and applicable':c['kept_applicable'],'Ranked first and inapplicable':c['kept_inapplicable'],
                       'Ranked lower and applicable':c['excluded_applicable'],'Ranked lower and inapplicable':c['excluded_inapplicable']}
                      for group,c in fit['source_rank_counts'].items()])
            st.caption("The first three manuscripts informed the ranking rule. The fourth was reserved for checking it. The rank is available for author inspection in the manuscript review workspace.")
    coverage_path=DATA/'eval-frozen/metrics/coverage.json'
    if coverage_path.exists():
        with st.expander("How many planned evaluations have a result?"):
            coverage=json.loads(coverage_path.read_bytes())
            st.write(f"The comparison covers {coverage['planned']} planned reports across four methods.")
            names={'A':'Direct review','B':'Whole-paper retrieval','C':'Trigger retrieval','D':'Verified review'}
            st.table([{'Method':names[r['method']],'Judged':r['judged'],'Awaiting judgment':r['awaiting_judgment'],
                       'Recorded failure':r['recorded_failure'],'Awaiting result':r['awaiting_result'],
                       'Failures with supplemental output':r['supplemental']} for r in coverage['methods']])
            st.caption("Each supplemental output belongs to a recorded failure. The paired comparison uses the original protocol.")
            if failures:=coverage.get('failures'):
                recovered={(item['paper'],item['method']) for item in coverage['recoveries']}
                if st.checkbox("Inspect the original failed attempts"):
                    st.dataframe([{'Manuscript':titles.get(f['paper'],f['paper']),'Method':names[f['method']],
                                   'Original error':'Invalid JSON after two attempts' if f['invalid_json'] else f['error'],
                                   'Supplemental report':'Available' if (f['paper'],f['method']) in recovered else 'No output yet'}
                                  for f in failures],hide_index=True)
            if recoveries:=coverage.get('recoveries'):
                bound=sum(item['manuscript_hash_recorded'] for item in recoveries)
                st.caption(f"{bound} of {len(recoveries)} supplemental reports record a manuscript checksum verified against the frozen PDF. Earlier reports without a checksum are counted separately.")
                st.dataframe([{'Manuscript':item['paper'],'Method':names[item['method']],
                               'Calls recovered with shorter instructions':item['shortened_calls'],
                               'Supplemental predictions':item.get('semantic_counts',{}).get('predictions'),
                               'Published concerns recovered':f"{item['semantic_counts']['matched_references']} / {item['semantic_counts']['references']}" if 'semantic_counts' in item else 'Awaiting score',
                               'Manuscript checksum':'Verified' if item['manuscript_hash_recorded'] else 'Unavailable'}
                              for item in recoveries],hide_index=True)
            delivery=coverage.get('delivery_recall')
            if delivery and delivery['papers']:
                st.write("How many published concerns reached the author when a report could fail?")
                st.caption(f"All four methods have a judged report or a recorded failure on these {delivery['papers']} manuscripts. A failed original run delivered zero concerns. The denominator includes all {delivery['published_concerns']} published concerns on these papers.")
                st.table([{'Method':names[method],'Returned reports':row['delivered_reports'],
                           'Reports raising a concern':row.get('reports_with_predictions'),
                           'Reports recovering a published concern':row.get('reports_with_match'),
                           'Failed reports':row['failed_reports'],'Published concerns recovered':row['recovered'],
                           'End-to-end recall':f"{row['recall']:.1%}" if row['recall'] is not None else 'Undefined'}
                          for method,row in delivery['methods'].items()])
    version_results=DATA/'eval-frozen/metrics/paired-by-input-version.json'
    if version_results.exists():
        with st.expander("Manuscript versions in the held-out review experiment"):
            by_version=json.loads(version_results.read_bytes())
            st.table([{"Input version":name,"Selected papers":group["eligible"],"Papers with all methods judged":group["papers"]}
                      for name,group in by_version.items()])
            st.caption("A later PDF can incorporate reviewer feedback. PDF creation dates and archived review timestamps identify this risk. Results on earlier versions are evaluated separately.")
            version_pairs=DATA/'eval-early/metrics/version-pairs.json'
            if version_pairs.exists():
                versions=json.loads(version_pairs.read_bytes())
                if versions.get('by_method'):
                    st.write(f"Which published concerns were recovered from each version? The paired check covers {versions['semantically_judged_pairs']} paper–method pairs across {versions['distinct_papers_judged']} manuscripts.")
                    method_names={'A':'Direct review','B':'Whole-paper retrieval','C':'Trigger retrieval','D':'Verified review'}
                    st.table([{'Method':method_names[m],'Paired papers':r['papers'],'Primary PDF only':r['primary_only'],
                               'Both PDFs':r['both'],'Pre-review PDF only':r['early_only']} for m,r in versions['by_method'].items()])
                    st.caption("Each count is a distinct published concern for one manuscript and method. Each pair uses two different PDFs, the same review protocol and the same published reviewer concerns.")
    st.stop()
if activity=="Lab meeting":
    st.header("Research group workspace")
    files=st.file_uploader("Group papers and meeting notes",type=['pdf','txt','md'],accept_multiple_files=True)
    if files and st.button("Save uploads to local lab library"):
        try:
            save_documents([(f.name,f.getvalue()) for f in files])
            st.success("Saved to this computer’s lab library.")
        except Exception as exc:st.error(str(exc))
    if saved_name:=st.session_state.pop("new-meeting-record",None):
        st.success(f"Decision saved. Select {saved_name} for the next brief.")
    library=list_documents()
    selected=st.multiselect("Saved lab documents",library,format_func=lambda item:f"{item[0]} · {item[1][:8]}") if library else []
    task_names={'question':'Q&A','related-work-gap':'Related work','reviewer-2':'Reviewer #2','weekly-brief':'Weekly brief','summary':'Paper summary'}
    mode=st.radio("Task",list(task_names),format_func=task_names.get,horizontal=True)
    if mode=='summary':
        render_summary(files,selected,model_label)
        st.stop()
    use_demo=st.checkbox("Use the public research-group example")
    public_path=DATA/'lab-replays'/(mode+'.json')
    public=json.loads(public_path.read_bytes()) if use_demo and public_path.is_file() else None
    q=st.text_area("Question or meeting topic",value=public['question'] if public else "",
                   key=f"lab-topic-{mode}-{use_demo}")
    sources={f"{name} [{digest[:8]}]":digest for name,digest in selected}
    for upload in files:
        digest=hashlib.sha256(upload.getvalue()).hexdigest()
        sources[f"{upload.name} [{digest[:8]}]"]=digest
    demo_ids=[]
    demo_note=DATA/'lab-pilot/group-evaluation-note.md'
    if use_demo:
        demo_ids=([Path(name).stem for name in public['documents']] if public else
                  sorted({r['paper_id'] for r in json.loads((DATA.parent/'eval/lab_qa.json').read_text())}))
        for i in demo_ids:
            name=i+'.pdf'
            sources[name]=hashlib.sha256((DATA/'iclr2023'/name).read_bytes()).hexdigest()
        if mode=='weekly-brief':
            notes=public.get('meeting_records',{}) if public else {}
            if notes:demo_note=DATA/next(iter(notes.values()))['path']
            if demo_note.is_file():sources[demo_note.name]=hashlib.sha256(demo_note.read_bytes()).hexdigest()
    names=list(sources)
    manuscript=st.selectbox("Draft to check for related work",names) if mode=='related-work-gap' and names else None
    meeting_records=[]
    if mode=='weekly-brief' and names:
        meeting_records=st.multiselect("Meeting records documenting group work",names,
            default=[n for n in names if n.rsplit(' [',1)[0].lower().endswith(('.md','.txt'))],
            help="Select the records for a group progress meeting. Leave this empty for a literature discussion.")
    lab_inputs=[mode,q,sources,manuscript,sorted(meeting_records)]
    labkey="lab-"+fingerprint(lab_inputs)
    public_result=public_lab_result(public,lab_inputs) if public else None
    has_local=demo_path('lab',lab_inputs).is_file()
    live,demo=action_buttons("Prepare answer","lab-"+mode,available=has_local or public_result is not None,
                             disabled=not names or not q.strip())
    if demo:
        st.session_state[labkey]=load_demo('lab',lab_inputs) if has_local else public_result
        st.session_state[labkey+'-demo']=True
    if live:
        docs=read_documents(selected)
        try:
            for f in files:
                content=f.getvalue()
                docs[f"{f.name} [{hashlib.sha256(content).hexdigest()[:8]}]"]=document(f.name,content)
        except Exception as exc:
            st.error(str(exc));st.stop()
        if use_demo:
            docs.update({i+'.pdf':parse_pdf((DATA/'iclr2023'/(i+'.pdf')).read_bytes()) for i in demo_ids})
        if use_demo and mode=='weekly-brief' and demo_note.is_file():docs[demo_note.name]=document(demo_note.name,demo_note.read_bytes())
        st.session_state[labkey]=call(run_lab(q,docs,mode,manuscript,meeting_records))
        st.session_state[labkey+'-demo']=False
        if st.session_state[labkey]:
            remember_demo('lab',lab_inputs,st.session_state[labkey])
            st.rerun()
    if result:=st.session_state.get(labkey):
        if st.session_state.get(labkey+'-demo'):st.caption("Demo · saved lab meeting result")
        uploads={f"{f.name} [{hashlib.sha256(f.getvalue()).hexdigest()[:8]}]":f for f in files if f.name.lower().endswith('.pdf')}
        stored={f"{n} [{d[:8]}]":d for n,d in selected if n.lower().endswith('.pdf')}
        demo_files={i+'.pdf' for i in demo_ids}
        for point_number,p in enumerate(result['points']):
            if heading:=p.get('heading'):
                st.subheader(heading)
            if p['sources']:
                st.write(p['text'])
            else:
                st.caption(p['text'])
                st.caption('No linked passage. Check this statement before use.')
            for source_number,s in enumerate(p['sources']):
                with st.expander(f"{s['file']} · page {s['page']} · {s['id']}"):
                    st.write(s['text'])
                    name=s['file']
                    if name in uploads or name in stored or name in demo_files:
                        if st.checkbox("Show original PDF page",key=f"{labkey}-{point_number}-{source_number}-{s['id']}"):
                            if name in uploads:source=uploads[name].getvalue()
                            elif name in demo_files:source=(DATA/'iclr2023'/name).read_bytes()
                            else:source=saved_pdf(stored[name])
                            if source:st.image(highlight(source,s['page'],s['text']),width=650)
                            else:st.caption("Save the original PDF again to display the page image for this older library entry.")
        for s in result['external']:
            st.link_button(s['title'],s['url'])
            pages=s.get('title_match_pages',[])
            match='Title found on p. '+', '.join(map(str,pages)) if pages else 'Exact title not found in the draft'
            st.caption(f"{s['catalog']} · {s['published']} · {match}")
        result_hash=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
        decision_key=f'{labkey}-{result_hash}-agreed-decision'
        agreed=st.session_state.get(decision_key)
        if agreed:
            st.subheader("Decision agreed by the group")
            st.write(agreed)
        st.download_button("Download meeting notes",meeting_markdown(q,result,agreed),"meeting.md",on_click="ignore")
        with st.expander("Record a decision for the next meeting"):
            with st.form('meeting-decision-'+decision_key):
                decision=st.text_area("Decision agreed by the group",placeholder="Which action did you agree to, and who will follow up?")
                save_decision=st.form_submit_button("Save decision to local library")
            if save_decision:
                if decision.strip():
                    filename='meeting-decision-'+date.today().isoformat()+'.md'
                    note=f"# Group meeting decision\n\nTopic: {q}\n\n{decision.strip()}\n"
                    references=dict.fromkeys((s['file'],s['page']) for pt in result['points'] for s in pt['sources'])
                    if references:
                        note+='\nSources shown in the meeting workspace\n'+''.join(f'- {name}, p. {page}\n' for name,page in references)
                    save_documents([(filename,note.encode())])
                    st.session_state[decision_key]=decision.strip()
                    st.session_state["new-meeting-record"]=filename
                    st.rerun()
                else:st.info("Enter the agreed decision before saving.")

        with st.expander("Tool calls"):st.json(result['tools'])
    st.stop()
samples=sorted(manifest(2025),key=lambda r:(r["id"]!="k2ZVAzVeMP",r["title"]))
selection=st.sidebar.selectbox("Manuscript",["Upload a PDF"]+[r['title'] for r in samples],key="current_manuscript")
sample=next((r for r in samples if r['title']==selection),None)
if sample and sample.get('version'):st.caption(sample['version'])
if sample and sample.get('timing_audit')=='PDF created on or after first review':
    st.caption("This PDF was generated after reviewing began. It may contain revisions responding to feedback.")
if sample:content=(DATA/'iclr2025'/(sample['id']+'.pdf')).read_bytes()
else:
    f=st.file_uploader("Manuscript PDF",type="pdf")
    if not f:st.info("Upload a manuscript or select a public paper in the sidebar. For the prepared demo, choose Efficient Dictionary Learning with Switch Sparse Autoencoders.");st.stop()
    content=f.getvalue()
try:paper=parse_pdf(content)
except Exception as exc:st.error(str(exc));st.stop()
venues=['ICLR','NeurIPS']
if activity=="Manuscript review":
    venue=st.sidebar.selectbox("Target venue",venues,index=venues.index(st.session_state.get('last_review_venue','ICLR')),key="review_venue")
    st.session_state['last_review_venue']=venue
cutoff=st.sidebar.date_input("Prior work published before",value=date(2024,10,1) if sample else date.today())
if activity=="Rebuttal":
    st.header("Rebuttal workbench")
    if sample:paper['title']=sample['title']
    example=""
    if sample:
        truth_path=DATA/'truth-labels'/(sample['id']+'.json')
        if truth_path.exists() and st.checkbox("Use an actual reviewer comment"):
            example=json.loads(truth_path.read_text())[0]['quote']
    text=st.text_area("Paste reviewer comments",value=example)
    replay_file=DATA/'rebuttal-replays'/(paper['hash']+'-'+hashlib.sha256(text.encode()).hexdigest()+'.json')
    comment_hash=hashlib.sha256(text.encode()).hexdigest()
    rkey=f"rebuttal-{paper['hash']}-{cutoff}-{comment_hash}"
    for prefix in ('','works-'):
        if prefix+rkey not in st.session_state:
            for previous in dict.fromkeys([st.session_state.get('last_review_venue','ICLR'),*venues]):
                old=f"{prefix}{paper['hash']}-{previous}-{cutoff}{comment_hash}"
                if old in st.session_state:
                    st.session_state[prefix+rkey]=st.session_state[old]
                    break
    reply_inputs=[paper['hash'],comment_hash]
    works_inputs=[*reply_inputs,cutoff.isoformat()]
    run_works,show_works=action_buttons("Check works mentioned by the reviewer","rebuttal-works",
        available=demo_path('works',works_inputs).is_file(),disabled=not text.strip())
    if run_works or show_works:
        reading=(load_demo('works',works_inputs) if show_works else call(inspect_comparison(paper,text,cutoff.isoformat(),ask)))
        st.session_state['works-'+rkey]=reading
        st.session_state['works-demo-'+rkey]=show_works
        if run_works and reading:
            remember_demo('works',works_inputs,reading)
            st.rerun()
    if reading:=st.session_state.get('works-'+rkey):
        if st.session_state.get('works-demo-'+rkey):st.caption("Demo · saved comparison check")
        render_comparisons(content,reading)
    run_reply,show_reply=action_buttons("Draft point-by-point reply","rebuttal-reply",
        available=demo_path('reply',reply_inputs).is_file() or replay_file.is_file(),disabled=not text.strip())
    if run_reply or show_reply:
        if run_reply:
            reply=call(rebuttal(paper,text))
            if reply:remember_demo('reply',reply_inputs,reply)
        else:
            reply=load_demo('reply',reply_inputs)
            if reply is None:
                stored=json.loads(replay_file.read_bytes())
                if [stored['manuscript_sha256'],stored['review_sha256']]==reply_inputs:
                    reply=stored['result']
                else:st.warning("Saved reply does not match this manuscript and comment.")
        st.session_state[rkey]=reply
        st.session_state['reply-demo-'+rkey]=show_reply
        if run_reply and reply:st.rerun()
    if result:=st.session_state.get(rkey):
        if st.session_state.get('reply-demo-'+rkey):st.caption('Demo · saved rebuttal draft')
        for item in result['responses']:
            a=item['answer'];st.subheader(item['critique'])
            st.caption(' · '.join(s for s in (item.get('category'),a['action'].capitalize()) if s))
            if 'next_step' in a:
                if source:=a.get('existing_evidence'):
                    st.markdown("**Existing manuscript evidence**")
                    st.write(source['quote'])
                    st.caption(f"Page {source['page']} · {source.get('role','')}")
                st.markdown("**Suggested next step**")
                st.write(a['next_step'])
                st.markdown("**Response to reviewer**")
            st.write(a['draft'])
            for name,counts in item.get('strategy_outcomes',{}).items():
                linked=[h for h in item['history'] if h.get('reply_strategy')==name]
                replies=len({h['reply_id'] for h in linked if h.get('reply_id')})
                st.caption(f"{name.capitalize()} · Distinct replies: {replies} · Linked concerns: {len(linked)} · Concerns with a documented outcome: {counts['known_outcomes']} · Recorded as resolved: {counts['resolved']}")
            with st.expander("Manuscript evidence and previous responses"):
                for ev in item['evidence']:show_evidence(content,ev)
                for h in item['history']:
                    st.markdown(h['title'])
                    st.link_button('Historical reviewer comment',h['source'])
                    if h.get('reply_id') and h.get('paper_id'):
                        st.link_button('Historical author reply',f"https://openreview.net/forum?id={h['paper_id']}&noteId={h['reply_id']}")
                    try:reply=json.loads(h['reply'])
                    except (TypeError,ValueError):reply=h['reply']
                    if isinstance(reply,dict):reply=reply.get('Comment') or reply.get('Response') or reply
                    st.write(reply)
                    if h.get('reply_strategy_quote'):
                        st.caption("Author wording for the response strategy")
                        st.write(h['reply_strategy_quote'])
                    if h.get('resolution_quote') and type(h.get('resolved')) is bool:
                        state='resolved' if h['resolved'] else 'unresolved'
                        st.caption(f"Reviewer wording for the recorded outcome · {state}")
                        st.write(h['resolution_quote'])
        st.subheader("Experiment checklist")
        steps=experiment_checklist(result['responses'])
        for a in steps:
            action=f"Priority {a.get('priority','unassigned')} · effort {a.get('effort','to estimate')} · {a['experiment']}"
            st.write(action)
        st.download_button("Download Markdown",rebuttal_markdown(result["responses"]),"rebuttal.md")
    st.stop()
key=f"{paper['hash']}-{venue}-{cutoff}"
st.header(sample['title'] if sample else f.name)
if paper.get('sections'):
    with st.expander("Manuscript sections"):
        st.dataframe([{'Section':s['heading'],'First page':s['start_page'],'Last page':s['end_page']} for s in paper['sections']],hide_index=True)
scope_key='scope-'+paper['hash']
scope=st.session_state.get(scope_key)
review_inputs=[paper['hash'],venue,cutoff.isoformat()]
saved_review_path=review_demo_path(*review_inputs,sample_id=sample['id'] if sample else None)
saved_scope=read_scope_demo(paper['hash'],saved_review_path,venue,cutoff.isoformat())
reading_job='reading-'+paper['hash']
future=st.session_state.get(reading_job)
read_live,read_demo=action_buttons("Read claims and experimental settings","manuscript-reading",
    available=saved_scope is not None,disabled=future is not None)
if read_demo:
    scope=st.session_state[scope_key]=saved_scope
    st.session_state[scope_key+'-demo']=True
if read_live or future is not None:
    if read_live:
        st.session_state[scope_key+'-demo']=False
        pool=ThreadPoolExecutor(max_workers=1)
        future=pool.submit(asyncio.run,inspect_manuscript(paper))
        pool.shutdown(wait=False)
        st.session_state[reading_job]=future
    if future is not None and future.done():
        del st.session_state[reading_job]
        try:
            claims,paper_type,settings=future.result()
            scope=dict(manuscript_sha256=paper['hash'],claims=claims,paper_type=paper_type,settings=settings,declared_limitations=declared_limitations(paper))
            st.session_state[scope_key]=scope
            remember_demo("reading",[paper["hash"]],scope)
            st.rerun()
        except Exception as exc:
            st.session_state[reading_job+'-error']=str(exc)
            st.rerun()
    elif future is not None:
        @st.fragment(run_every=2)
        def reading_progress():
            if future.done():st.rerun()
            st.caption("Reading claims and checking them against the PDF…")
        reading_progress()
if reading_error:=st.session_state.pop(reading_job+'-error',None):
    st.error(f"The manuscript reading could not finish. {reading_error}")
if scope is not None:
    if st.session_state.get(scope_key+"-demo"):st.caption("Demo · saved manuscript reading")
    render_scope(content,scope)
jobkey="job-"+key
job=st.session_state.get(jobkey)
run_live,run_demo=action_buttons("Run three reviewers","manuscript-review",available=saved_review_path is not None,
    disabled=job is not None,primary=True)
if run_demo:
    st.session_state.pop(key+'-chair-demo',None)
    st.session_state[key]=read_review_demo(saved_review_path,*review_inputs)
    st.session_state[key+'-demo']=True
if run_live:
    st.session_state.pop(key+'-chair-demo',None)
    st.session_state[key+'-demo']=False
    st.session_state.pop(key,None)
    updates=Queue()
    pool=ThreadPoolExecutor(max_workers=1)
    future=pool.submit(asyncio.run,run_review(paper,venue,before=cutoff.isoformat(),progress=updates.put,prepared_reading=scope,on_stage=updates.put))
    pool.shutdown(wait=False)
    st.session_state[jobkey]=dict(future=future,updates=updates,events=[],started=time.monotonic())
    st.rerun()
if job and not job['future'].done():
    @st.fragment(run_every=1)
    def progress_panel():
        while True:
            try:event=job['updates'].get_nowait()
            except Empty:break
            if isinstance(event,dict) and 'fraction' in event:
                job['stage']=event
            else:job['events'].append(event)
        if job['future'].done():st.rerun()
        elapsed=int(time.monotonic()-job['started'])
        stage=job.get('stage',dict(fraction=0.,label="Starting review"))
        st.progress(stage['fraction'],text=f"{stage['label']} · {elapsed} s")
        for event in job['events']:
            if isinstance(event,dict):
                with st.expander(event['role'],expanded=True):st.write(event['report'].get('summary',''))
            else:st.caption(event)
    progress_panel()
if job and job['future'].done():
    try:
        completed=job['future'].result()
        st.session_state[key]=completed
        if not completed['meta_review'].get('error'):
            remember_demo('review',review_inputs,completed)
    except Exception as exc:st.session_state[jobkey+'-error']=str(exc)
    del st.session_state[jobkey]
    st.rerun()
if error:=st.session_state.pop(jobkey+'-error',None):st.error(error)
result=st.session_state.get(key)
if result:
    if st.session_state.get(key+"-demo"):
        st.caption("Demo · saved reviewer reports")
    else:
        st.progress(1.0,text="Review complete · 3/3 reviewers finished")
    rubric=result.get('rubric') or {}
    labels={str(k):v for k,v in rubric.get('score_labels',{}).items()}
    if not labels and rubric.get('year')==2025:
        labels={str(k):v for k,v in SCORE_LABELS.get(result['venue'],{}).items()}
    if rubric:
        scale=' · '.join(f"{x} {labels.get(str(x),'')}".strip() for x in rubric['scores'])
        st.caption(f"{result['venue']} {rubric['year']} reviewer scale · {scale}")
        st.link_button("Venue review guide",rubric['source'])
    st.subheader("Area chair recommendation")
    meta=result['meta_review']
    if st.session_state.get(key+'-chair-demo'):st.caption("Demo · saved area chair recommendation")
    if meta.get('rationale_version')!=2:
        chair_key=chair_inputs(review_inputs,result)
        saved_chair=load_demo('chair',chair_key)
        run_chair,show_chair=action_buttons(f"Generate AC recommendation with {model_label}","manuscript-chair",
            available=saved_chair is not None)
        if run_chair or show_chair:
            revised=saved_chair if show_chair else call(chair_recommendation(result['venue'],result['reviews'],
                result.get('claims'),decision=meta.get('recommendation'),novelty=result.get('contribution_comparisons'),
                research_value=result.get('research_value')))
            if revised:
                if run_chair:remember_demo('chair',chair_key,revised)
                result['meta_review']=meta=revised
                st.session_state[key+'-chair-demo']=show_chair
                if run_chair:remember_demo('review',review_inputs,result)
                st.rerun()
    if meta.get('recommendation') in ('Accept','Reject'):
        st.markdown(f"**{meta['recommendation']}** · simulated decision")
    elif meta.get("error"):
        st.warning(meta["error"])
    else:
        st.caption("This earlier review contains a synthesis only.")
    if meta.get('rationale_version')==2:
        label='Why accept' if meta['recommendation']=='Accept' else 'Why reject'
        st.markdown(f'**{label}**')
        st.write(meta['impact'])
        finding=meta['decisive_finding']
        pages=', '.join(map(str,finding['pages']))
        st.caption('Supporting evidence'+(f' · p. {pages}' if pages else ''))
        st.write(finding['statement'])
    else:
        st.write(meta.get('summary',''))
    for col,r in zip(st.columns(3),result['reviews']):
        with col.container(border=True):
            st.subheader(r['role'])
            report=r['report']
            score=report.get('score')
            if score is None:
                score=report.get('score_status') or 'Reviewer did not provide a rating'
                if report.get('summary')=='No supported concerns assigned to this reviewer.':
                    score='Unrated · no verified concern assigned'
            label=labels.get(str(score))
            st.caption(f"Score · {score} ({label})" if label else f"Score · {score}")
            st.write(report.get('summary',''))
            if report.get('score_rationale'):st.write(report['score_rationale'])
            if check:=report.get('rating_check'):
                with st.expander("Evidence affecting the rating"):
                    for passage in check['evidence']:
                        st.caption(f"Page {passage['page']}")
                        st.write(passage['quote'])
            if 'investigation' in report:
                with st.expander("Reviewer investigation"):
                    if not report['investigation']:
                        st.caption("No additional tool calls recorded.")
                    for step in report['investigation']:
                        st.write(step['question'])
                        st.caption(f"{step['tool']} · {step['argument']}")
                        for observation in step['results']:
                            if 'url' in observation:
                                st.markdown(f"[{observation['title']}]({observation['url']})")
                            else:
                                st.caption(f"Page {observation['page']}")
                            st.write(observation['quote'])
            with st.expander("Read review"):
                if grades:=report.get('criteria'):
                    for criterion,value in grades.items():
                        st.write(criterion.capitalize()+' · '+(f'{value}/4' if value is not None else 'Unrated'))
                for field in ('strengths','weaknesses','weakness','weaknesss','questions'):
                    if report.get(field):
                        st.markdown('**'+field.capitalize()+'**')
                        render_text(report[field])
    if result.get('method')=='D' and 'contribution_comparisons' in result:
        with st.expander("Originality and prior work",expanded=True):
            if value:=result.get('research_value'):
                st.markdown("**Research value**")
                st.write(value['value'])
                st.caption(f"Page {value['page']} · {value['quote']}")
            comparisons=result['contribution_comparisons']
            if not comparisons:
                st.caption("No page-grounded contribution available for comparison.")
            for row in comparisons:
                st.markdown(f"**Page {row['page']} · {row['status'].replace('_',' ')}**")
                st.write(row['claim'])
                if row.get('comparison'):st.write(row['comparison'])
                if row.get('title'):
                    st.markdown(f"[{row['title']}]({row['url']})")
                    if row.get('prior_source'):
                        origin=row.get('catalog') or 'Publication'
                        link="Listed in manuscript references" if row.get('cited_in_manuscript') else "Literature search"
                        st.caption(f"{origin} · {row['published']} · {link}" if origin!='OpenReview' else "Local OpenReview abstract")
                        source_label=row['prior_source']+(f" · p. {row['prior_page']}" if row.get('prior_page') else "")
                        source_url=row['prior_url']
                        if row.get('prior_page'):
                            source_url=source_url.partition('#')[0]+f"#page={row['prior_page']}"
                        st.markdown(f"[{source_label}]({source_url})")
                    st.caption(row['prior_quote'])
                    if anchor:=row.get('citation_in_manuscript'):
                        st.caption(f"How the manuscript cites this work · p. {anchor['page']}")
                        st.write(anchor['quote'])
                if row.get('validation'):
                    st.write(f"Evidence on page {row['validation_page']} · {row['validation']}")
                elif row['status']=='distinct':
                    st.caption("Direct validation of the difference was not identified.")
                elif row['status']=='Insufficient evidence':
                    st.caption("The available passages did not establish a specific relationship for this claim.")
            if 'prior_searches' in result:
                with st.expander("Literature searches"):
                    for search in result['prior_searches']:
                        outcome=(f"{search['matches']} matching records" if search['status']=='complete' else "Catalog unavailable")
                        st.write(f"{search['kind'].capitalize()} · {search['query']} · {outcome}")
    if conflicts:=result.get('manuscript_conflicts'):
        with st.expander("Manuscript consistency checks",expanded=True):
            for finding in conflicts:
                st.write(finding['issue'])
                for source in finding['evidence']:
                    st.caption(f"Page {source['page']}")
                    st.write(source['quote'])
    if examples:=result.get('comparison_reviews'):
        with st.expander("Historical OpenReview comparisons"):
            for item in examples:
                st.link_button(item['venue']+' · '+item['title'],item['source'])
                st.write(item['review_excerpt'])
    if scope is None:
        render_scope(content,result)
    questions=author_questions(paper,result['checked'])
    if questions:
        with st.expander(f"Open questions for the authors ({len(questions)})"):
            st.caption("The verifier could not fully resolve these questions. Record the evidence or revision decision for each one.")
            scope_id=hashlib.sha256(json.dumps(questions,sort_keys=True).encode()).hexdigest()
            notes_key=key+'-author-questions-'+scope_id
            if st.button("Compare question wording with historical reviews",key=notes_key+'-rank'):
                from reviewarena.question_alignment import source_ranks
                candidates=[item['candidate'] for item in result['checked']]
                st.session_state[notes_key+'-ranks']={(candidates[i]['target_question'],candidates[i]['source']):rank
                                                     for i,rank in source_ranks(candidates).items()}
            if paper.get('captions'):
                if st.button("Find figures and tables for these questions",key=notes_key+'-find'):
                    from reviewarena.verifier import find_captions
                    st.session_state[notes_key+'-captions']=find_captions(paper,[row['question'] for row in questions])
                for row,hits in zip(questions,st.session_state.get(notes_key+'-captions',[])):
                    st.write(row['question'])
                    for caption in hits:
                        with st.expander(f"{caption['label']} · p. {caption['page']}"):
                            show_evidence(content,dict(caption,reason='Retrieved caption for manual inspection'))
                    row['captions']=hits
            with st.form(notes_key):
                meeting_notes=[]
                for row in questions:
                    st.write(row['question'])
                    st.caption(f"Manuscript p. {row['page']} · "+row['claim'])
                    for passage in row['evidence']:
                        st.caption(f"Partial answer, p. {passage['page']} · "+passage['quote'])
                    if rank:=st.session_state.get(notes_key+'-ranks',{}).get((row['question'],row['source'])):
                        row['source_rank']=rank
                        st.write("Retrieved reviewer quotation")
                        st.write(row['source_quote'])
                        if rank.get('historical_question'):
                            st.caption('Historical question used for retrieval · '+rank['historical_question'])
                        st.caption(f"The assigned historical question ranks {rank['rank']} of {rank['compared']} when the proposed question is searched against this manuscript's retrieved candidates. Closest category: {rank['closest_category']}.")
                    st.markdown("[Historical reviewer comment]("+row['source']+")")
                    note_key=key+'-author-note-'+hashlib.sha256(row['question'].encode()).hexdigest()
                    note=st.text_area("Evidence or revision decision",key=note_key,placeholder="Record a page, experiment or action for the next draft.")
                    meeting_notes.append(dict(row,note=note))
                prepare=st.form_submit_button("Prepare author notes")
            if prepare:
                st.session_state[notes_key+'-prepared']=author_question_notes(
                    meeting_notes,manuscript=sample['title'] if sample else f.name,pdf_sha256=paper['hash'])
            if prepared:=st.session_state.get(notes_key+'-prepared'):
                st.download_button("Download prepared author notes",prepared,f"author-questions-{paper['hash'][:12]}.md",on_click="ignore")
    for item in result['checked']:
        c=item['candidate']
        with st.expander(item['status']+' · '+c['category']):
            if c.get('matched_claim'):
                st.caption('Manuscript claim that triggered retrieval')
                st.write(c['matched_claim'])
                if c.get('matched_claim_page'):
                    st.caption(f"Manuscript page {c['matched_claim_page']}")
            if c.get('family'):st.caption('Historical critique family · '+c['family'])
            if 'prior_total' in c:
                st.caption(f"Retrieval score {c['score']:.3f} · trigger similarity {c['similarity']:.3f} · historical severity {c['severity']}/3")
                if c['prior_total']:
                    cohort=' / '.join(x for x in (c['matched_claim_type'],c['matched_paper_type']) if x)
                    if 'prior_reviews' in c:
                        st.caption(f"{c['prior_reviews']} of {c['prior_total']} distinct labeled reviews in the {cohort} cohort raised this family of concerns.")
                    else:
                        st.caption(f"{c['prior_issues']} of {c['prior_total']} labeled issues in the {cohort} cohort belonged to this family.")
            if c.get('family_assignment'):
                st.caption(f"Critique family · {c['family']} ({c['family_assignment']})")
            if c.get('family_fit_reason'):st.caption('Family assignment audit · '+c['family_fit_reason'])
            if c.get('target_question'):st.markdown('**Question for this manuscript** · '+c['target_question'])
            if c.get('transfer_question'):st.caption('Historical question · '+c['transfer_question'])
            st.caption('Historical reviewer comment')
            st.write(c['critique_text'])
            if c.get('review_id') and st.toggle("Read the surrounding review text",key="review-field-"+paper['hash']+c['id']):
                section=historical_review_section(c['paper_id'],c['review_id'],c['critique_text'])
                if section:
                    st.caption(section[0])
                    st.text(section[1])
                else:
                    st.caption("The archived field could not be located. Open the historical review below.")
            if item.get('reason'):st.caption(item['reason'])
            if check:=item.get('comparison_check'):
                st.caption(check['status'])
                for work in check['works']:
                    rec=work['record']
                    st.link_button(rec['title']+' · '+rec['published'],rec['url'])
            current_column,history_column=st.columns(2)
            with current_column:
                st.markdown("**Current manuscript**")
                for ev in item['evidence']:show_evidence(content,ev)
                if not item['evidence']:
                    if c.get('matched_claim') and c.get('matched_claim_page'):
                        if st.toggle("Show the claim in this draft",key="current-"+paper['hash']+c['id']):
                            show_evidence(content,dict(page=c['matched_claim_page'],quote=c['matched_claim'],reason="Claim that triggered retrieval"))
                    st.caption("No manuscript passage was accepted as evidence for a criticism.")
            with history_column:
                st.markdown("**Historical manuscript**")
                st.link_button(f"Historical review · {c['year']} · manuscript p. {c['trigger_page']}",c['source'])
                st.write(c['trigger_text'])
                pdf_info=c.get('pdf_info') or {}
                historical_pdf=DATA/pdf_info['file'] if pdf_info.get('file') else DATA/f"iclr{c['year']}"/(c['paper_id']+'.pdf')
                if pdf_info.get('version'):st.caption(pdf_info['version'])
                if historical_pdf.is_file() and st.toggle("Show historical manuscript page",key="historical-"+paper['hash']+c['id']):
                    st.image(highlight(historical_pdf.read_bytes(),c['trigger_page'],c['trigger_text']),width=600)
    outcome=result['historical_outcome']
    if outcome and outcome['papers']:
        st.caption(f"Historical acceptance in matched labeled papers: {outcome['accepted']}/{outcome['papers']}. Descriptive, uncalibrated.")
        if 'matched_papers' in outcome:
            excluded=outcome['matched_papers']-outcome['papers']
            st.caption(f"{excluded} matched manuscripts lacked a recorded main-track acceptance or rejection and were excluded from the denominator.")
    elif outcome is not None:
        if outcome.get('matched_papers',0):
            st.caption(f"Historical acceptance unavailable. None of the {outcome['matched_papers']} matching manuscripts had a recorded main-track acceptance or rejection.")
        elif any(item['status']=='valid' for item in result['checked']):
            st.caption("Historical acceptance unavailable. No usable acceptance or rejection was available for the matched concerns.")
        else:
            st.caption("Historical acceptance unavailable. The verifier found no supported concern to use for matching historical papers.")
    with st.expander("Tool calls and prior publications"):st.json(result['tools']);st.json(result['sources'])
    if sample and st.toggle("Reveal actual reviews and decision",key="truth-"+key):
        import duckdb,re
        with duckdb.connect() as db:
            record=db.execute("select decision,reviews from read_parquet(?) where paper_id=? and year='2025'",[str(DATA/'raw/reviews.parquet'),sample['id']]).fetchone()
        st.subheader("Published review outcome")
        st.write(record[0] if record else sample['decision'])
        comparison=DATA/'metrics/scale-version-evidence.json'
        if comparison.exists():
            scale=json.loads(comparison.read_bytes())
            if sample['id']==scale['paper'] and paper['hash']==scale['later']['sha256']:
                with st.expander("Did the model-scale evidence change after review?"):
                    st.caption(f"Public preprint posted {scale['posted'][:10]} · reviewer comment {scale['reviewed'][:10]}")
                    st.write(scale['reviewer_quote'])
                    st.link_button('Read this reviewer’s original comment',scale['review_url'])
                    choice=st.radio('Manuscript evidence',['Pre-review preprint','Later public manuscript','Later results table'],
                                    horizontal=True,key=key+'-scale-version')
                    part={'Pre-review preprint':'before','Later public manuscript':'later','Later results table':'table'}[choice]
                    ev=scale[part]
                    raw=(DATA/ev['file']).read_bytes()
                    if hashlib.sha256(raw).hexdigest()==ev['sha256']:
                        show_evidence(raw,dict(ev,reason=choice))
                    else:
                        st.error('The source PDF has changed since the comparison was verified.')
                    st.caption("The preprint describes experiments on GPT-2 Small. The later manuscript also reports one Gemma 2 2B layer. The added run extends the tested range. Generalization to larger backbone models remains open.")
                    if results:=scale.get('trigger_retrieval'):
                        stated=lambda item: 'matched' if item['found'] else 'did not match'
                        st.caption(f"In the frozen experiment, trigger retrieval {stated(results['earlier'])} this published concern on the early preprint and {stated(results['later'])} it on the later manuscript. This is one version pair.")
        if record:
            def numeric_score(value):
                match=re.match(r"^\s*(\d+(?:\.\d+)?)",str(value))
                return float(match.group(1)) if match else None
            labels=["Simulated mean","Published mean"] if venue=="ICLR" else ["NeurIPS simulated mean","ICLR published mean"]
            for column,label,values in zip(st.columns(2),labels,
                                           [[r['report'].get('score') for r in result['reviews']],
                                            [r.get('rating') for r in record[1]]]):
                scores=[n for value in values if (n:=numeric_score(value)) is not None]
                column.metric(label,f"{sum(scores)/len(scores):.2f}" if scores else "Abstained")
                column.caption(f"{len(scores)} scored reviews")
            st.json(record[1],expanded=False)
        archive=DATA/'iclr2025/chair_decisions.parquet'
        if archive.exists():
            with duckdb.connect() as db:
                chair=db.execute('select note_id,writer,content from read_parquet(?) where paper_id=? order by time desc',[str(archive),sample['id']]).fetchall()
            if chair:
                with st.expander("Published chair decision and rationale"):
                    for note,writer,raw in chair:
                        st.link_button(writer.replace('_',' '),f"https://openreview.net/forum?id={sample['id']}&noteId={note}")
                        for field,value in json.loads(raw).items():
                            if field.casefold() in ('title','decision'):continue
                            st.markdown('**'+field+'**')
                            render_text(value)
