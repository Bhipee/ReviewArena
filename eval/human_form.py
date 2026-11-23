"""Build standalone blind review forms from the already sampled, source-verified pairs."""
import argparse
import hashlib
import json
from pathlib import Path
from run import DATA


def publish(root):
    folder=root/'human-audit'
    sample=json.loads((folder/'sample-key.json').read_bytes())
    pairs=[]
    for idx,row in enumerate(sample):
        paper,method,i,j=row['pair_id'].split('/')
        raw=(root/'judge-input'/paper/(method+'.json')).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['packet_sha256']:raise ValueError('Changed sample packet')
        packet=json.loads(raw)
        ref=packet['reference'][int(j)]
        if packet['predicted'][int(i)]!=row['prediction'] or ref['paraphrase']!=row['review_critique'] or not ref['quote'].strip():
            raise ValueError('Changed or missing source text')
        review=json.loads((root/paper/'truth.json').read_bytes())['reviews'][ref['review_index']]
        if not any(isinstance(text,str) and ref['quote'] in text for text in review.values()):
            raise ValueError('Quotation cannot be found in the original review for '+paper)
        pairs.append(dict(sample_id=idx,prediction=row['prediction'],review_critique=row['review_critique'],quote=ref['quote']))
    if len(pairs)!=100:raise ValueError('Expected the 100-pair blind sample')
    template=Path(__file__).with_name('human_form.html').read_text()
    data=json.dumps(pairs,ensure_ascii=False).replace('<','\\u003c')
    sample_hash=hashlib.sha256(data.encode()).hexdigest()
    for rater in ('rater1','rater2'):
        (folder/(rater+'.html')).write_text(template.replace('RATER_ID',rater).replace('SAMPLE_HASH',sample_hash).replace('SAMPLE_JSON',data))
    print('Published two independent forms for',len(pairs),'pairs')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',default='eval-frozen')
    args=parser.parse_args()
    publish(DATA/args.run)
