"""Compare passages from the same manuscript before reviewers assign scores."""
import asyncio
import re
from itertools import combinations

CHECKS = {
    "protocol": (
        r"frozen|freez\w*|fine[- ]tun\w*|jointly|held fixed|trainable|data split|held[- ]out|training stage",
        "Compare the training or evaluation instructions. Check the same stage, components and setting. "
        "Different stages or different components can be compatible."
    ),
    "results": (
        r"\bTable\s+\d+[a-z]?\s*[:.]\s",
        "Read both tables' row and column headers. Compare the same named method, dataset and metric, "
        "including a macro average reported in a per-class table. Distinguish aggregates from individual class scores. "
        "If comparable numbers differ, state both values and whether the paper explains the change."
    ),
}
STOP=set("the this with and from that for not are have table during after before method more than stage these training results".split())


def excerpts(pages,kind,pattern):
    rows=[]
    for page_number,page in enumerate(pages,1):
        if kind=='protocol':
            passages=(s for s in re.split(r'(?<=[.!?])\s+',page) if re.search(pattern,s,re.I))
        else:
            marks=list(re.finditer(pattern,page,re.I))
            passages=(page[m.start():min(m.start()+1800,marks[i+1].start() if i+1<len(marks) else len(page))]
                      for i,m in enumerate(marks))
        for passage in passages:
            if kind=='protocol' and len(passage)>800:
                hit=re.search(pattern,passage,re.I)
                passage=passage[max(0,hit.start()-230):hit.end()+450]
            if len(passage.strip())>=16:
                rows.append(dict(page=page_number,quote=passage.strip()))
    return rows


def training_states(row):
    text=row['quote'].lower()
    if re.search(r"\b(?:ablation|unlike|alternatively|instead of|not|never)\b",text):return {}
    ordinal={"first":"1","second":"2","third":"3"}
    stage=re.search(r"\b(?:stage|phase)\s+(\d+)|\b(first|second|third) (?:training )?(?:stage|phase)",text)
    if not stage:return {}
    number=stage[1] or ordinal[stage[2]]
    states={}
    for component in ("encoder","decoder","backbone","classifier","transformer","embedding"):
        for occurrence in re.finditer(r"\b"+component+r"s?\b",text):
            after=text[occurrence.end():occurrence.end()+65]
            before=text[max(0,occurrence.start()-80):occurrence.start()]
            if re.match(r"(?: and (?:the )?[a-z]+s?)? (?:weights |parameters )?(?:(?:remain|are|were|is|kept) )?(?:frozen|fixed)",after):
                states[(number,component)]='frozen'
            elif re.search(r"(?:optimized|trained|updated) jointly with (?:the )?$",before) or re.match(r" (?:weights |parameters )?(?:are |were )?(?:updated|fine-tuned|trained)\b",after):
                states[(number,component)]='updated'
    return states


def compare_macro_to_overview(tables,detail,names,targets):
    """Match complete multi-dataset column headers before comparing reported values."""
    findings=[]
    caption=detail['caption']
    for table in tables:
        cells=[c for c in table['cells'] if not c.isdigit()]
        if not cells or cells[0].lower() not in ('method','model'):continue
        first=next((i for i,c in enumerate(cells) if re.fullmatch(r"\d+\.\d+[†‡*]?",c)),None)
        if first is None:continue
        headers=cells[1:first-1]
        for cut in range(1,len(headers)):
            cohorts,metrics=headers[:cut],headers[cut:]
            width=len(metrics)
            if not width or width%len(cohorts):continue
            stride=width//len(cohorts)
            if len(cohorts)<2 or metrics!=metrics[:stride]*len(cohorts):continue
            for j,cohort in enumerate(cohorts):
                terms=set(re.findall(r'[a-z0-9]+',cohort.lower()))-{'iv','iii','ii','dataset'}
                if not terms or not terms.issubset(set(re.findall(r'[a-z0-9]+',caption.lower()))):continue
                for k,metric in enumerate(metrics[:stride]):
                    if not re.search(r'\b'+re.escape(metric)+r'\b',caption,re.I):continue
                    differences=[]
                    evidence_rows=[]
                    for name,target in zip(names,targets):
                        row=next((i for i in range(first-1,len(cells)-width)
                                  if re.sub(r'\s*\(ours\)$','',cells[i],flags=re.I).casefold()==name.casefold()),None)
                        if row is None:continue
                        value=cells[row+1+j*stride+k].rstrip('†‡*')
                        if not re.fullmatch(r'\d+\.\d+',value) or float(value)==float(target):continue
                        differences.append(f"{name} {value} vs {target}")
                        evidence_rows.append(' '.join(cells[row:row+1+width]))
                    if differences:
                        findings.append(dict(kind='scope_check',
                            issue=f"The overview and per-class tables report different {metric} values for overlapping {cohort} labels ({', '.join(differences)}). Check whether the cohorts and averaging rules match before interpreting this as a contradiction.",
                            evidence=[dict(page=table['page'],quote=table['caption']+' | '+' '.join(headers)+' | '+' | '.join(evidence_rows)),dict(page=detail['page'],quote=caption+' | '+' '.join(names)+' | Macro Average '+' '.join(targets))]))
            break
    return findings


def macro_checks(tables):
    findings=[]
    for table in tables:
        caption=table['caption']
        size=re.search(r"\b(\d+)[- ](?:class|label)\b",caption,re.I)
        if re.search(r"weighted|pooled",caption,re.I):continue
        if not size or not re.search(r"per[- ]class",caption,re.I):continue
        cells=[c for c in table['cells'] if not c.isdigit()]
        end=next((i for i,c in enumerate(cells) if c.casefold() in ("macro average","macro mean")),None)
        if end is None:continue
        numeric=r"-?\d+\.\d+"
        first=next((i for i,c in enumerate(cells[:end]) if re.fullmatch(numeric,c)),None)
        if first is None:continue
        names=cells[1:first-1]
        width=len(names)
        if not width or end-first+1!=int(size[1])*(width+1):continue
        rows=[cells[i:i+width+1] for i in range(first-1,end,width+1)]
        targets=cells[end+1:end+1+width]
        if len(targets)!=width or not all(re.fullmatch(numeric,c) for c in targets+[v for row in rows for v in row[1:]]):continue
        findings.extend(compare_macro_to_overview(tables,table,names,targets))
        issues=[]
        for col,(name,target) in enumerate(zip(names,targets),1):
            values=[r[col] for r in rows]
            mean=sum(map(float,values))/len(rows)
            tolerance=sum(0.5*10**-len(v.split('.')[1]) for v in values)/len(rows)+0.5*10**-len(target.split('.')[1])
            if abs(mean-float(target))>tolerance+1e-10:
                issues.append(f"{name}: mean {mean:.4f}, reported {target}")
        if issues:
            findings.append(dict(kind='results',issue=f"{caption} The {len(rows)} displayed class rows do not reproduce the stated macro average within rounding ("+'; '.join(issues)+').',
                                 evidence=[dict(page=table['page'],quote=caption+' '+ ' | '.join(cells[:end+1+width]))]))
    return findings


async def check_manuscript(paper,ask):
    async def examine(kind,instruction,left,right):
        answer=await ask(instruction+
            " Determine whether there is a material internal conflict. Check alternatives such as a different cohort, metric, "
            "time point or training stage. Do not interpret missing detail alone as a contradiction. "
            "Return a flat JSON object. First extract detail1 and detail2 (short exact substrings from "
            "the first and second passage showing the pertinent facts), and issue (one precise English sentence explaining "
            "the shared setting, both facts and the implication). Finally set relation to incompatible, compatible, or unclear, consistent with your explanation.",
            first=left,second=right)
        if str(answer.get('relation','')).strip().lower()!='incompatible':return None
        issue=answer.get('issue')
        if not isinstance(issue,str) or not issue.strip():return None
        evidence=[]
        for n,row in enumerate((left,right),1):
            detail=answer.get(f'detail{n}')
            if not isinstance(detail,str):return None
            detail=' '.join(detail.split())
            if len(detail)<3 or detail not in row['quote']:return None
            evidence.append(dict(page=row['page'],quote=row['quote'],detail=detail))
        if kind=='results':
            values=re.findall(r'\b\d+\.\d+\b',issue)
            if len(set(values))<2 or any(not any(v in r['quote'] for r in evidence) for v in values):return None
            if not all(any(v in r['detail'] for v in values) for r in evidence):return None
        return dict(kind=kind,issue=issue.strip(),evidence=evidence)

    direct=macro_checks(paper.get('tables',[]))
    jobs=[]
    for kind,(pattern,instruction) in CHECKS.items():
        rows=excerpts(paper['pages'],kind,pattern)
        if kind=='protocol':
            rows=[row for row in rows if training_states(row)]
        def features(row):
            return set(re.findall(r'[a-z][a-z0-9-]{2,}',row['quote'].lower()))-STOP
        tokens=[features(row) for row in rows]
        pairs=[]
        for a,b in combinations(range(len(rows)),2):
            shared=tokens[a]&tokens[b]
            if not shared or rows[a]['quote']==rows[b]['quote']:continue
            if kind=='protocol':
                first,second=training_states(rows[a]),training_states(rows[b])
                matches=[key for key in first.keys() & second.keys() if first[key]!=second[key]]
                if matches:
                    stage,component=sorted(matches)[0]
                    direct.append(dict(kind=kind,issue=f"Stage {stage}: the {component} is described as {first[(stage,component)]} on page {rows[a]['page']} and {second[(stage,component)]} on page {rows[b]['page']}. If both describe the reported model, these instructions imply different learned parameters; check the surrounding protocol for a variant.",evidence=[rows[a],rows[b]]))
                continue
            overlap=len(shared)/max(1,min(len(tokens[a]),len(tokens[b])))
            pairs.append((overlap,a,b))
        for _,a,b in sorted(pairs,reverse=True)[:5]:
            jobs.append(examine(kind,instruction,rows[a],rows[b]))
    return direct+[f for f in await asyncio.gather(*jobs) if f]
