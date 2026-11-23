"""Verify semantic judgments against the exact lab inference packets and aggregate them."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from run import DATA, write


def import_lab(directory):
    questions = json.loads(Path(__file__).with_name('lab_qa.json').read_text())
    accepted = {}
    ratings = {name: Counter() for name in ('baseline', 'rag', 'citations')}
    page_grades = {'cited': Counter(), 'not_cited': Counter()}
    for i, reference in enumerate(questions):
        key = f'{i:02}'
        raw = (DATA/'eval-lab'/f'{key}.json').read_bytes()
        packet = json.loads(raw)
        item = json.loads((directory/f'{key}.json').read_text())
        expected = (key, reference['paper_id'], reference['question'], reference['answer'],
                    hashlib.sha256(raw).hexdigest(), 'gpt-6-luna', 'xhigh')
        fields = ('item_id','paper_id','question','reference_answer','packet_sha256','model','effort')
        if packet['reference'] != reference or tuple(item.get(k) for k in fields) != expected:
            raise ValueError(f'{key}: mismatched packet, reference, or label provenance')
        for method in ('baseline', 'rag'):
            rating = item[method]
            if rating['label'] not in ('correct','partial','incorrect','missing') or not rating['explanation'].strip():
                raise ValueError(f'{key}: invalid answer judgment for {method}')
            ratings[method][rating['label']] += 1
        sources = {(s['id'],s['file'],s['page']) for p in packet['rag']['points'] for s in p['sources']}
        reference_page = (reference['paper_id'] + '.pdf', reference['page'])
        cited_pages = {(file, page) for _, file, page in sources}
        group = 'cited' if reference_page in cited_pages else 'not_cited'
        page_grades[group][item['rag']['label']] += 1
        citations = item['rag']['citations']
        if sources != {(s['id'],s['file'],s['page']) for s in citations} or len(sources) != len(citations):
            raise ValueError(f'{key}: citation coverage mismatch')
        for c in citations:
            if c['support'] not in ('supports','partially_supports','does_not_support') or not c['explanation'].strip():
                raise ValueError(f'{key}: invalid citation judgment')
            ratings['citations'][c['support']] += 1
        accepted[key] = item
    for key, item in accepted.items():
        write(DATA/'lab-judgments'/f'{key}.json', item)
    result = dict(questions=len(accepted), judge='gpt-6-luna', effort='xhigh',
                  papers=len({s['paper_id'] for s in questions}), answer_grades_by_reference_page=page_grades, **ratings)
    write(DATA/'metrics'/'lab-correctness.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    print(json.dumps(import_lab(parser.parse_args().directory), indent=2))
