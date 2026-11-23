"""Local blinded ScholarMate rating UI. Exported CSVs are accepted by lab_human.py."""
import csv
import hashlib
import io
import json
from pathlib import Path

import streamlit as st

from lab_human import assess
from run import DATA
from reviewarena.paper import highlight

FOLDER = DATA / 'eval-lab-human'
OPTIONS = {'answers': ['correct', 'partial', 'incorrect', 'missing'],
           'citations': ['supports', 'partially_supports', 'does_not_support']}


@st.cache_data
def source_packet():
    assess(FOLDER, False)
    refs = json.loads(Path(__file__).with_name('lab_qa.json').read_bytes())
    hashes = json.loads((FOLDER / 'source-pages.json').read_bytes())['manuscript_sha256']
    return refs, hashes


def read_sheet(content):
    return sorted(csv.DictReader(io.StringIO(content.decode('utf-8-sig'), newline='')), key=lambda r: int(r['sample_id']))


def export(rows):
    target = io.StringIO(newline='')
    writer = csv.DictWriter(target, fieldnames=rows[0])
    writer.writeheader()
    writer.writerows(rows)
    return target.getvalue()


st.set_page_config(page_title='ScholarMate human assessment')
st.title('ScholarMate human assessment')
kind = st.radio('Assessment', list(OPTIONS), format_func=str.title, horizontal=True)
refs, hashes = source_packet()
rows_key = kind + '-rows'
if rows_key not in st.session_state:
    st.session_state[rows_key] = read_sheet((FOLDER / (kind + '.csv')).read_bytes())
rows = st.session_state[rows_key]
keys = json.loads((FOLDER / (kind + '-key.json')).read_bytes())['ids']
resume = st.file_uploader('Resume from a saved CSV', type='csv', key=kind+'-resume')
if resume and st.button('Load ratings from '+resume.name):
    try:
        records = read_sheet(resume.getvalue())
        items = {r['sample_id']: r for r in records}
        if len(items) != len(records) or len(items) != len(rows):
            raise ValueError('The file has missing or duplicate items.')
        restored = []
        for original in rows:
            rated = items[original['sample_id']]
            if (set(rated) != set(original) or any(rated[k] != original[k] for k in original if k not in ('rating', 'reason'))
                    or rated['rating'] not in ['', *OPTIONS[kind]] or rated['reason'] is None):
                raise ValueError('The file differs from this assessment.')
            restored.append(rated)
        st.session_state[kind+'-loaded'] = resume.name
        st.session_state[rows_key] = restored
        st.session_state.pop(kind+'-rating', None)
        st.session_state.pop(kind+'-reason', None)
        st.rerun()
    except (ValueError, KeyError, UnicodeError, csv.Error) as exc:
        st.error(str(exc))

if restored_from := st.session_state.pop(kind+'-loaded', None):
    st.success('Restored ratings from '+restored_from)

def reset_editor():
    st.session_state.pop(kind+'-rating', None)
    st.session_state.pop(kind+'-reason', None)

index = st.selectbox('Item', range(len(rows)), format_func=lambda i: str(i+1), key=kind+'-index', on_change=reset_editor)
row = rows[index]
ref = refs[keys[int(row['sample_id'])]['question_index']]
st.caption(f"{sum(bool(r['rating'] and r['reason'].strip()) for r in rows)} of {len(rows)} rated with a reason")
st.subheader(row['question'])
if kind == 'answers':
    st.markdown('**Answer to assess**')
    st.write(row['answer'] or '(Empty answer)')
    st.markdown('**Reference answer**')
    st.write(row['reference_answer'])
    filename, page, quote = ref['paper_id']+'.pdf', ref['page'], ref['quote']
else:
    st.markdown('**Claims supported by this citation**')
    st.write(row['claims'])
    filename, page, quote = row['file'], int(row['page']), row['passage']
st.markdown(f'**Source passage · {filename} · page {page}**')
st.write(quote)
if st.toggle('Show original PDF page'):
    raw = (DATA / 'iclr2023' / filename).read_bytes()
    if hashlib.sha256(raw).hexdigest() != hashes[filename]:
        st.error('The PDF has changed since the assessment was prepared.')
    else:
        st.image(highlight(raw, page, quote), width='stretch')
with st.form(kind+'-form'):
    rating = st.selectbox('Rating', ['', *OPTIONS[kind]], index=(['', *OPTIONS[kind]]).index(row['rating']), key=kind+'-rating')
    reason = st.text_area('Reason', value=row['reason'], key=kind+'-reason')
    if st.form_submit_button('Record this rating'):
        if not rating or not reason.strip():
            st.error('Select a rating and give a reason.')
        else:
            row.update(rating=rating, reason=reason.strip())
            st.rerun()
st.download_button('Download my CSV', export(rows), file_name=kind+'.csv', mime='text/csv', on_click='ignore')
st.caption('Record each rating before moving to another item. Download the CSV to keep your work.')
