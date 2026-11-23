"""Build the supporting deck from the local corpus and verified annotation index."""
from pathlib import Path
import sys
import duckdb
from pptx import Presentation
from pptx.util import Inches,Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from reviewarena.kb import current_snapshot

snapshot=current_snapshot()
db=duckdb.connect(str(ROOT/'data/history.duckdb'),read_only=True)
paper_count,review_count=db.sql('select (select count(*) from papers),(select count(*) from reviews)').fetchone()
pairs,papers=db.execute("select count(*), count(distinct paper_id) from read_parquet(?)",[str(snapshot/'critique.parquet')]).fetchone()
largest_year,year_pairs=db.execute('select year,count(*) n from read_parquet(?) group by year order by n desc,year limit 1',[str(snapshot/'critique.parquet')]).fetchone()
labeled_reviews, families=db.execute('select count(distinct review_id), count(distinct family) from read_parquet(?)',[str(snapshot/'taxonomy.parquet')]).fetchone()
deck=Presentation();deck.slide_width=Inches(13.33);deck.slide_height=Inches(7.5)
def text(s,x,y,w,h,value,size=26,bold=False,color='233631'):
    shp=s.shapes.add_textbox(Inches(x),Inches(y),Inches(w),Inches(h))
    tf=shp.text_frame;tf.word_wrap=True;tf.vertical_anchor=MSO_ANCHOR.MIDDLE
    p=tf.paragraphs[0];p.text=value;p.font.name='Calibri';p.font.size=Pt(size);p.font.bold=bold;p.font.color.rgb=RGBColor.from_string(color)
    return shp
def slide(section,title):
    s=deck.slides.add_slide(deck.slide_layouts[6])
    s.background.fill.solid();s.background.fill.fore_color.rgb=RGBColor.from_string('F8F8F4')
    text(s,.72,.35,11,.35,section.upper(),13,True,'41735E')
    text(s,.72,.95,11.9,1.1,title,39,True)
    text(s,.72,6.96,11,.25,'COMP6708   /   Group 16',12,False,'54665E')
    return s
def rows(s,items):
    for n,(title,body) in enumerate(items):
        y=2.25+1.35*n;text(s,.75,y,3.0,1.06,title,24,True,'386652')
        text(s,4.05,y,8.45,1.06,body,23)
s=slide('Author & supervisor workspace','ReviewArena')
text(s,.78,2.42,11.6,1.25,'Which criticism should we act on before submission?',36)
text(s,.78,4.36,10.65,.93,'A historical review suggests a question. The manuscript supplies the evidence.',26,False,'416E59')
s=slide('Historical evidence','Where the review questions come from')
for x,value,label in [(0.75,f'{paper_count:,}','historical papers'),(5.0,f'{review_count:,}','official reviews'),(9.05,str(pairs),'verified pairs')]:
    text(s,x,2.36,3.75,1.06,value,44,True,'386652');text(s,x,3.49,3.75,.58,label,21)
text(s,.75,4.66,11.7,1.18,f'{labeled_reviews:,} reviews contain issues classified into {families} families. Page-linked examples cover {papers} papers. {year_pairs:,} of {pairs:,} pairs come from {largest_year}.',23)
case_file=ROOT/'data/metrics/verifier-response-evidence.json'
if case_file.exists():
    import json
    case=json.loads(case_file.read_text())
    s=slide('Historical reviewer exchange','What changed when the authors supplied timings?')
    current_file=ROOT/'data/metrics/verifier-response-evidence-current.json'
    if current_file.exists():
        cases=json.loads(current_file.read_text())['conditions']
        rows(s,[('Author’s claim','The manuscript calls the overhead reasonable. The verifier found no measured comparison in that excerpt.'),
                ('Pruning time','CIFAR-10: NTK-SAP took 17 s and Iterative SNIP took 24 s. The verifier marked this question '+cases['pruning_only_with_table']['status']+'.'),
                ('End-to-end time','Same two methods and same dataset. The table measures pruning. The verifier marked total training time '+cases['matched_end_to_end_with_table']['status']+'.')])
    else:
        rows(s,[('Reviewer concern','Iterative pruning may cost substantially more than alternative methods.'),
                ('Manuscript excerpt','The authors call the overhead reasonable. The verifier could not substantiate a timing comparison from this excerpt.'),
                ('Published reply','The authors supplied a table of pruning times. The verifier marked the comparison addressed. Total training cost remains a separate question.')])
    text(s,.77,6.37,11.8,.33,'NTK-SAP · ICLR 2023 · OpenReview forum -5EWhW_4qWP · author reply VaHn_2Hrok5',14,False,'66756B')
else:
    s=slide('Historical example','What would substantiate an efficiency claim?')
    rows(s,[('The claim','A model aims to reduce computational cost.'),('Reviewer concern','How much time does the model save at comparable performance?'),('What to check','Find the timing comparison and its experimental conditions in the new manuscript and appendix.')])
    text(s,.77,6.37,11.8,.33,'ICLR 2023 · OpenReview forum yIxtevizEA · review los-4aq8a8R',14,False,'66756B')
s=slide('Live workflow','From a candidate concern to a review decision')
rows(s,[('Retrieve','Use a claim to find historical trigger passages with a pretrained BGE encoder.'),('Verify','Search the current manuscript for supporting evidence and counterexamples. Preserve page and passage identifiers.'),('Review','A local 4-bit Qwen2.5-3B-Instruct runs three reviewer roles. A chair prompt summarizes supported findings.')])
s=slide('Rebuttal','Turn a review into a decision about revision')
rows(s,[('Clarify','Quote the relevant result and give its location in the draft.'),('Run an experiment','List the measurement that would resolve the question and keep it in future tense.'),('Revise','Acknowledge a limitation or narrow a claim. The author checks the response before use.')])
frozen_pairs,frozen_papers=db.execute("select count(*),count(distinct paper_id) from read_parquet(?)",[str(ROOT/'data/eval-frozen/indexes/critique.parquet')]).fetchone()
s=slide('Evaluation','How to tell whether verification helped')
rows(s,[('Held-out sample','50 ICLR 2025 papers, balanced by decision. Real reviews and decisions are opened after inference.'),('Four conditions',f'Direct review, whole-paper retrieval, trigger retrieval, and verified review. The two trigger methods used {frozen_pairs} fixed passage–critique pairs from {frozen_papers} papers.'),('Interpretation','Inspect precision, recall, page evidence and abstentions. All 25 accepted PDFs and one rejected PDF were created on or after the first review. Revision timing can confound acceptance prediction.')])
pilot=ROOT/'data'/'judge-input'/'k2ZVAzVeMP'
judges=ROOT/'data'/'judgments'/'k2ZVAzVeMP'
import json
paired_path=ROOT/'data/eval-frozen/metrics/paired.json'
paired=json.loads(paired_path.read_text()) if paired_path.exists() else {}
if paired.get('papers') and not paired.get('multiple_protocols_within_method'):
    n=paired['papers']
    selected=set(paired['paper_ids'])
    inputs=json.loads((ROOT/'data/iclr2025/manifest.json').read_bytes())
    rejected=sum(p['decision']=='Reject' for p in inputs if p['id'] in selected)
    s=slide('Matched test cases · frozen protocol','Which review concerns were recovered?')
    text(s,.78,2.00,12,.52,f"{n} of {len(inputs)} manuscripts have four scored reports · {n-rejected} accepted, {rejected} rejected",21,True,'416E59')
    labels={'A':'Direct review','B':'Whole-paper retrieval','C':'Trigger retrieval','D':'Verified review'}
    for x,w,heading in [(.77,4.50,'Method'),(5.23,3.05,'Matched predictions'),(8.54,3.68,'Recovered issues')]:
        text(s,x,2.61,w,.56,heading,18,True)
    for i,(method,label) in enumerate(labels.items()):
        row=paired['methods'][method];y=3.22+.59*i
        text(s,.77,y,4.6,.54,label,21)
        precision=f"{row['matched_predictions']} / {row['predictions']}" if row['predictions'] else 'No predictions'
        text(s,5.23,y,3.0,.54,precision,21)
        text(s,8.54,y,3.68,.54,f"{row['matched_references']} / {row['references']}",21)
    silent=paired['methods']['D']['no_prediction_papers']
    coverage_file=paired_path.with_name('coverage.json')
    note=f'Verified review raised no concerns on {silent} of {n} manuscripts.'
    if coverage_file.exists():
        coverage=json.loads(coverage_file.read_bytes())
        failed=sum(row['recorded_failure'] for row in coverage['methods'])
        delivery=coverage.get('delivery_recall',{})
        verified=delivery.get('methods',{}).get('D',{})
        if failed and 'reports_with_predictions' in verified:
            note=(f"Across {delivery['papers']} manuscripts with four known outcomes, verified review returned "
                  f"{verified['delivered_reports']} reports, raised concerns in {verified['reports_with_predictions']} "
                  f"and failed on {verified['failed_reports']}.")
        elif failed:
            note+=f' The study has recorded {failed} failed report attempts.'
    text(s,.78,5.77,11.8,.76,note,18,False,'416E59')
    text(s,.78,6.55,11.6,.27,f'ICLR 2025 · frozen trigger index: {frozen_pairs} pairs · semantic judgments by gpt-6-luna, xhigh',12,False,'66756B')
elif (judges/'A.json').exists() and (judges/'D.json').exists():
    import json,hashlib
    items=[]
    for method in ('A','D'):
        raw=(pilot/(method+'.json')).read_bytes()
        packet=json.loads(raw);judge=json.loads((judges/(method+'.json')).read_text())
        if judge['packet_sha256']!=hashlib.sha256(raw).hexdigest():raise ValueError('Pilot judgment is stale')
        items.append((len(packet['predicted']),len({j for _,j in judge['matches']}),len(packet['reference'])))
    s=slide('Pilot result · one manuscript','What happened on Switch Sparse Autoencoders?')
    a,d=items
    rows(s,[('Direct review',f'{a[0]} predicted concerns matched {a[1]} of {a[2]} reference issues.'),
            ('Verified review',f'{d[0]} concerns passed the pilot verifier. It recovered {d[1]} of {d[2]} reference issues and abstained from scoring.'),
            ('Next test','Measure whether exact page evidence and transferable questions improve recall across the balanced 50-paper sample.')])
    text(s,.75,6.38,11.7,.30,'ICLR 2025 · k2ZVAzVeMP · Pilot labels and semantic matches by gpt-6-luna, xhigh',13,False,'66756B')
lab_result=ROOT/'data/metrics/lab-correctness.json'
if lab_result.exists():
    import json
    lab=json.loads(lab_result.read_text())
    pages=json.loads((ROOT/'data/metrics/lab-pages.json').read_text())
    s=slide('Appendix · research group workspace','How well did the answers hold up?')
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN
    text(s,.75,2.02,11.8,.52,f"Answer quality across {lab['questions']} questions",23,True)
    palette={'correct':'356B56','partial':'E2CF93','incorrect':'974A42'}
    for row,(key,label) in enumerate([('baseline','Direct answer'),('rag','With retrieval')]):
        y=2.74+.81*row
        text(s,.78,y,2.45,.60,label,21,True)
        left=3.25
        for grade,color in palette.items():
            count=lab[key].get(grade,0)
            if not count:continue
            width=8.75*count/lab['questions']
            rect=s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(left), Inches(y), Inches(width), Inches(.60))
            rect.fill.solid();rect.fill.fore_color.rgb=RGBColor.from_string(color)
            rect.line.fill.background()
            labelbox=text(s,left,y,width,.60,f'{count} {grade}',19,True,'24372B' if grade=='partial' else 'FFFFFF')
            labelbox.text_frame.paragraphs[0].alignment=PP_ALIGN.CENTER
            left+=width
    total=sum(lab['citations'].values())
    text(s,.75,4.54,11.7,.90,f"Of {total} cited passages, {lab['citations']['supports']} supported the answer, {lab['citations']['partially_supports']} partly supported it and {lab['citations']['does_not_support']} gave no support.",24)
    text(s,.75,5.48,11.7,.55,f"{pages['citing_reference_page']} of {pages['completed']} answers cited the reference document and page.",21,False,'416E59')
    text(s,.77,6.38,11.7,.30,'Four public papers · same local model for both conditions · semantic labels by gpt-6-luna, xhigh',13,False,'66756B')
deck.save(ROOT/'demo/Assignment3-Group16.pptx')
