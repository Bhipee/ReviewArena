"""Locate manuscript sections in PDF reading order, retaining original page positions."""
import re

UNNUMBERED={'abstract','introduction','background','related work','method','methods',
            'methodology','experiments','evaluation','results','discussion','limitations',
            'conclusion','conclusions','references','bibliography','appendix',
            'acknowledgments','acknowledgements','reproducibility statement','ethics statement'}
NUMBERED=re.compile(r'^((?:[1-9]\d?(?:\.\d+){0,3}|[A-Z](?:\.\d+){0,2}))\.?\s+([A-Z][A-Za-z][^.!?;]{1,100})$')


def heading(line):
    phrase=' '.join(line.split())
    if phrase.casefold() in UNNUMBERED:return phrase
    match=NUMBERED.fullmatch(phrase)
    if not match:return None
    number,name=match.groups()
    if len(name.split())>12 or len(name)<3 or any(c in name for c in ',=()[]'):return None
    if re.match(r'(?:In Section|We |Let |Given |Suppose |If |Thus |Then |Step [0-9])',name,re.I):return None
    if number.isalpha() and not (name.isupper() or re.match(r'^\s*[A-Z](?:\.|\s{2,})',line)):return None
    return phrase


def section_map(raw_pages):
    sections=[];current=None
    for page,raw in enumerate(raw_pages,1):
        for line in raw.splitlines():
            title=heading(line)
            if title:
                if current is not None:sections.append(current)
                current=dict(heading=title,start_page=page,end_page=page,excerpt='')
            elif current is not None and line.strip():
                current['end_page']=page
                if len(current['excerpt'])<600:
                    current['excerpt']=(current['excerpt']+' '+' '.join(line.split())).strip()[:600]
    if current is not None:sections.append(current)
    return sections
