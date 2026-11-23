"""Bind the Switch SAE scale concern to the actual reviewer and two dated public manuscripts."""
import json
from datetime import datetime, timezone

import duckdb
from run import DATA, write
from reviewarena.paper import parse_pdf
from version_pairs import judgment, sha


def stored(manifest, pid):
    return next(row for row in json.loads((DATA/manifest).read_bytes()) if row['id']==pid)


def extract(entry, path, page, quote):
    source=(DATA/path).read_bytes()
    parsed=parse_pdf(source)
    if parsed['hash']!=entry['sha256'] or quote not in parsed['pages'][page-1]:
        raise ValueError(f'Manuscript or cited passage changed in {path}')
    return dict(file=path,sha256=parsed['hash'],page=page,quote=quote)


def main():
    paper='k2ZVAzVeMP'
    early=stored('iclr2025-early/manifest.json',paper)
    later=stored('iclr2025/manifest.json',paper)
    audit=stored('metrics/heldout-input-versions.json',paper)
    reference=json.loads((DATA/'truth-labels'/(paper+'.json')).read_bytes())[23]
    rid='J6xM2pBHg6'
    with duckdb.connect() as db:
        time,content=db.execute("select time,content from read_parquet(?) where review_openreview_id=? and replyto_openreview_id=?",
                                [str(DATA/'raw/notes-*.parquet'),rid,paper]).fetchone()
    if not any(reference['quote'] in text for text in json.loads(content).values() if isinstance(text,str)):
        raise ValueError('The selected reviewer quotation is missing')
    posted=datetime.fromisoformat(early['posted'].replace('Z','+00:00')).astimezone(timezone.utc)
    if posted.replace(tzinfo=None)>=datetime.fromisoformat(str(time)) or early['sha256']==later['sha256']:
        raise ValueError('The chronology does not establish distinct manuscript versions')
    first=extract(early,early['path'],5,'We train sparse autoencoders on the residual stream activations of GPT-2 small (Radford et al., 2019), which have a dimension of 768.')
    path='iclr2025/'+paper+'.pdf'
    second=extract(later,path,7,'We also train on a single layer of Gemma 2 2B (Team et al., 2024).')
    row=extract(later,path,15,'Gemma 2 2B 12 resid 0.961 0.955 0.991 0.989')
    matched={}
    baseline=None
    for label,folder,entry in [('later','eval-frozen',later),('earlier','eval-early',early)]:
        root=DATA/folder
        raw=(root/paper/'C.json').read_bytes()
        report=json.loads(raw)
        if baseline is None:
            baseline=report['protocol']
        elif baseline!=report['protocol']:
            raise ValueError('Different review protocols for the two manuscript versions')
        if label=='earlier':
            binding=json.loads((root/paper/'C.input.json').read_bytes())
            if (binding['output_sha256'],binding['input_sha256'])!=(sha(raw),entry['sha256']):
                raise ValueError('Wrong earlier manuscript or output')
        matches=judgment(root,paper,'C',report)
        if matches is None:
            raise ValueError('Missing matching assessment for '+label)
        matched[label]={'found':23 in matches,'report_sha256':sha(raw)}
    write(DATA/'metrics/scale-version-evidence.json',dict(paper=paper,review_id=rid,reviewed=str(time),
          reviewer_quote=reference['quote'],review_url=f'https://openreview.net/forum?id={paper}&noteId={rid}',
          posted=early['posted'],early_url=early['source'],later_url=later['url'],later_timing=audit['timing'],
          before=first,later=second,table=row,trigger_retrieval=matched))
    print(first['page'],second['page'],row['page'],str(time))


if __name__=='__main__':
    main()
