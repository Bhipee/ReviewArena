"""Import model-labeled match pairs after verifying the exact input packets."""
import argparse,hashlib,json,tempfile
from pathlib import Path
from run import DATA,write

def identified_packet(packet):
    """Label the two independent sequences so equal numeric positions carry no signal."""
    displayed={};positions={}
    for name in ('predicted','reference'):
        displayed[name]=[]
        positions[name]={}
        for index,item in enumerate(packet[name]):
            raw=json.dumps([name,index,item],ensure_ascii=False,sort_keys=True).encode()
            key=name[0]+'-'+hashlib.sha256(raw).hexdigest()[:16]
            if key in positions[name]:
                raise ValueError('Duplicate assessment identifier')
            positions[name][key]=index
            displayed[name].append(dict(id=key,content=item))
    return displayed,positions


def validate(judgment, raw, source):
    if (judgment.get('model'), judgment.get('effort')) != ('gpt-6-luna', 'xhigh'):
        raise ValueError(f'Unexpected model or reasoning effort in {source}')
    if judgment.get('packet_sha256') != hashlib.sha256(raw).hexdigest():
        raise ValueError(f'Input changed for {source}')
    packet = json.loads(raw)
    matches = judgment.get('matches')
    if not isinstance(matches, list):
        raise ValueError(f'Expected a list of matches in {source}')
    for pair in matches:
        if not isinstance(pair, list) or len(pair) != 2 or any(type(i) is not int for i in pair):
            raise ValueError(f'Expected two integer indices in {source}')
        i, j = pair
        if not (0 <= i < len(packet['predicted']) and 0 <= j < len(packet['reference'])):
            raise ValueError(f'Out-of-range match in {source}')
    if 'match_evidence' in judgment:
        evidence=judgment['match_evidence']
        if not isinstance(evidence,list) or len(evidence)!=len(matches):
            raise ValueError(f'Missing matched excerpts in {source}')
        displayed,_=identified_packet(packet)
        for (i,j),pair in zip(matches,evidence):
            pred=packet['predicted'][i]
            if isinstance(pred,dict) and isinstance(pred.get('text'),str):
                pred=pred['text']
            if not isinstance(pred,str):
                pred=json.dumps(pred,ensure_ascii=False)
            for kind,name,index,content in [('prediction','predicted',i,pred),
                                            ('reference','reference',j,packet['reference'][j]['quote'])]:
                excerpt=pair.get(kind+'_excerpt')
                if (pair.get(kind+'_id')!=displayed[name][index]['id'] or
                        not isinstance(excerpt,str) or not excerpt.strip() or excerpt not in content):
                    raise ValueError(f'{kind} excerpt or identifier differs from indexed text in {source}')
    return packet


def import_judgments(directory,paper,root=DATA):
    pending=[]
    for f in sorted(directory.glob('*.json')):
        if f.stem not in ('A','B','C','D'):continue
        packet_path=root/'judge-input'/paper/f.name
        raw=packet_path.read_bytes();judgment=json.loads(f.read_text())
        validate(judgment,raw,f)
        pending.append((f.name,judgment))
    for name,item in pending:
        current=root/'judgments'/paper/name
        if current.exists():
            previous=current.read_bytes()
            old=json.loads(previous)
            if old==item:continue
            revision=root/'judgment-revisions'/paper/Path(name).stem/(hashlib.sha256(previous).hexdigest()+'.json')
            revision.parent.mkdir(parents=True,exist_ok=True)
            if not revision.exists():
                with tempfile.NamedTemporaryFile(dir=revision.parent,delete=False) as file:
                    file.write(previous)
                    tmp=Path(file.name)
                tmp.replace(revision)
            elif revision.read_bytes()!=previous:
                raise ValueError(f'Archived judgment differs from its checksum: {revision}')
        write(current,item)
    return len(pending)
if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('directory',type=Path);parser.add_argument('paper', nargs='?');parser.add_argument('--run',default='eval');args=parser.parse_args()
    root=DATA if args.run=='eval' else DATA/args.run
    if args.paper:
        count=import_judgments(args.directory,args.paper,root)
    else:
        papers=json.loads((DATA/'iclr2025/manifest.json').read_text())
        count=sum(import_judgments(args.directory/p['id'],p['id'],root) for p in papers if (args.directory/p['id']).is_dir())
    print('Imported',count,'method judgments')
