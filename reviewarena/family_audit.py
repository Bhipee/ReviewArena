"""Verify annotations that judge a historical example's assigned family."""
import hashlib
import json


def verify_ratings(raw,label):
    packet=json.loads(raw)
    if (label['packet_sha256'],label['model'],label['effort'])!=(hashlib.sha256(raw).hexdigest(),'gpt-6-luna','xhigh'):
        raise ValueError('Unverified assignment audit source or judge')
    ratings=label['ratings']
    if len(ratings)!=len(packet['items']) or any(type(r['i']) is not int for r in ratings) or {r['i'] for r in ratings}!=set(range(len(ratings))):
        raise ValueError('Incomplete or duplicate assignment ratings')
    for r in ratings:
        item=packet['items'][r['i']]
        if r['verdict'] not in ('fits','misleading','unclear') or not r['reason'].strip() or len(r['quote'])<12 or r['quote'] not in item['review_quote']:
            raise ValueError(f"Invalid source or verdict for assignment {r['i']}")
    return packet,ratings


def applicable_ratings(root,reference,assignments,details):
    current={(r['paper_id'],r['review_id'],r['category'],r['critique_text'],r['trigger_text']) for r in details}
    result={}
    for path in sorted(root.glob('*/judgment.json')):
        packet,ratings=verify_ratings(path.with_name('packet.json').read_bytes(),json.loads(path.read_bytes()))
        if packet['reference']!=reference:continue
        for rating in ratings:
            item=packet['items'][rating['i']]
            key=(item['paper_id'],item['review_id'],item['category'],item['review_quote'],item['manuscript_quote'])
            if key not in current or assignments[item['category']][0]!=item['family']:continue
            if key in result and result[key]['verdict']!=rating['verdict']:
                raise ValueError(f"Conflicting family audits for review {item['review_id']}")
            result[key]=dict(key=key,verdict=rating['verdict'],reason=rating['reason'],family=item['family'])
    return [result[k] for k in sorted(result)]
