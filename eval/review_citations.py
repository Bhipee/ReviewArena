"""Verify named comparisons in A and D reviews against bibliographic catalogs."""
import argparse
import asyncio
import hashlib
import json
from run import DATA,write
from pathlib import Path
from reviewarena.tools import connect
from reviewarena.named_works import lookup_title


def packets(root):
    for f in sorted(root.glob('*/[AD].json')):
        raw=f.read_bytes()
        review=json.loads(raw)
        reports=[r['report'] for r in review['reviews']]
        write(root/'citation-input'/f.parent.name/f.name,
              dict(reports=reports,run_sha256=hashlib.sha256(raw).hexdigest()))


def strings(value):
    if isinstance(value,str):
        yield value
    elif isinstance(value,dict):
        for child in value.values():yield from strings(child)
    elif isinstance(value,list):
        for child in value:yield from strings(child)


def attributed_comparisons(reports,label,f):
    names={}
    for row in label['named_comparisons']:
        index=row['reviewer_index'];quote=row['review_quote'];title=row['catalog_query'].strip()
        if type(index) is not int or not 0<=index<len(reports) or not title or not quote.strip() or not any(quote in s for s in strings(reports[index])):
            raise ValueError(f'Invalid comparison attribution: {f}')
        names.setdefault(title.casefold(),dict(title=title,quote=quote,reviewer_index=index))
    return names


def import_from(directory,root):
    for f in sorted(directory.glob('*/[AD].json')):
        relative=f.relative_to(directory)
        packet=(root/'citation-input'/relative).read_bytes()
        item=json.loads(f.read_text())
        if (item.get('packet_sha256')!=hashlib.sha256(packet).hexdigest() or
            item.get('run_sha256')!=json.loads(packet)['run_sha256'] or
            (item.get('model'),item.get('effort'))!=('gpt-6-luna','xhigh')):
            raise ValueError(f'Invalid source for {f}')
        attributed_comparisons(json.loads(packet)['reports'],item,f)
        write(root/'citation-labels'/relative,item)


def summarize(audits):
    row=dict(labeled_reports=0,reports_with_named_comparisons=0,named_comparisons=0,confirmed=0,unconfirmed=0,lookup_error=0)
    for comparisons in audits:
        row['labeled_reports']+=1
        row['reports_with_named_comparisons']+=int(bool(comparisons))
        row['named_comparisons']+=len(comparisons)
        for result in comparisons:
            row[result['catalog_status']]+=1
    completed=row['confirmed']+row['unconfirmed']
    row['confirmation_rate']=row['confirmed']/completed if completed else None
    return row


async def score(root):
    assessed={m:{} for m in 'AD'}
    async with connect('scholar',[]) as search:
        for f in sorted((root/'citation-labels').glob('*/[AD].json')):
            packet=(root/'citation-input'/f.parent.name/f.name).read_bytes()
            digest=hashlib.sha256(packet).hexdigest()
            label=json.loads(f.read_text())
            if (label.get('packet_sha256'),label.get('model'),label.get('effort'))!=(digest,'gpt-6-luna','xhigh'):
                raise ValueError(f'Unverified source or judge: {f}')
            names=attributed_comparisons(json.loads(packet)['reports'],label,f)
            audited=[]
            for row in names.values():
                status,exact=await lookup_title(search,row['title'],'2024-10-01')
                audited.append(dict(**row,catalog_status=status,catalog_record=exact))
            write(root/'citation-audit'/f.parent.name/f.name,dict(packet_sha256=digest,catalog_tool='resolve_paper_title',before='2024-10-01',comparisons=audited))
            assessed[f.stem][f.parent.name]=audited
    common=sorted(assessed['A'].keys() & assessed['D'].keys())
    totals={}
    for method,records in assessed.items():
        totals[method]=summarize(records.values())
        totals[method]['assessed_paper_ids']=sorted(records)
        totals[method]['same_manuscripts']=summarize(records[paper] for paper in common)
    write(root/'metrics'/'citation-confirmation.json',totals)
    print(totals)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',default='eval-frozen')
    parser.add_argument('--score',action='store_true')
    parser.add_argument('--import-labels',type=Path)
    args=parser.parse_args()
    root=DATA/args.run
    packets(root)
    if args.import_labels:import_from(args.import_labels,root)
    if args.score:asyncio.run(score(root))
