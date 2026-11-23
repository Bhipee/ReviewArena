import hashlib,re
import pymupdf
from .sections import section_map

CAPTION=re.compile(r'^(Figure|Fig\.|Table)\s+([A-Z]?\d+(?:\.\d+)*(?:[a-z])?)\s*[:.]\s+(?=\S)',re.I)


def parse_pdf(content):
    with pymupdf.open(stream=content,filetype="pdf") as pdf:
        raw=[p.get_text(sort=True) for p in pdf]
        pages=[" ".join(text.split()) for text in raw]
        status=re.compile(r"(?:published as a (?:conference|workshop) paper at|under review as a (?:conference|workshop) paper at|submitted to)\s+(?:ICLR|NeurIPS)\s*20\d{2}",re.I)
        pages=[status.sub("",page).strip() for page in pages]
        captions=[]
        tables=[]
        for number,page in enumerate(pdf,1):
            blocks=page.get_text('blocks',sort=True)
            for idx,block in enumerate(blocks):
                if block[6]==0 and re.match(r'^Table\s+\d+[a-z]?\s*[:.]',block[4],re.I):
                    cells=[]
                    for following in blocks[idx+1:idx+16]:
                        body=following[4].strip()
                        if following[6]!=0 or body.isdigit():continue
                        if CAPTION.match(body) or any(len(line)>100 for line in body.splitlines()):break
                        cells.extend(line.strip() for line in body.splitlines() if line.strip())
                    if cells:
                        tables.append(dict(page=number,caption=' '.join(block[4].split()),cells=cells))
                if block[6]!=0:continue
                quote=' '.join(block[4].split())
                match=CAPTION.match(quote)
                if match and 20<=len(quote)<=2400 and quote in pages[number-1]:
                    kind='Table' if match[1].lower()=='table' else 'Figure'
                    captions.append(dict(page=number,label=kind+' '+match[2],quote=quote))
    if not any(pages):raise ValueError("This PDF has no extractable text. Upload a searchable PDF.")
    return {"hash":hashlib.sha256(content).hexdigest(),"pages":pages,"captions":captions,"tables":tables,"sections":section_map([status.sub("",text) for text in raw])}

def is_manuscript_title(title,first_page):
    def folded(text):
        return ' '.join(re.findall(r"\w+",text.casefold()))
    title=folded(title)
    if not title:return False
    opening=folded(first_page[:800])
    position=(' '+opening+' ').find(' '+title+' ')
    return 0<=position<=100

def highlight(content,page,quote):
    with pymupdf.open(stream=content,filetype="pdf") as pdf:
        p=pdf[page-1];rects=p.search_for(quote) if quote.strip() else []
        if not rects:
            # Search smaller exact spans across column breaks and PDF hyphenation.
            words=quote.split()
            for i in range(0,len(words),7):
                phrase=' '.join(words[i:i+7])
                matches=p.search_for(phrase)
                if len(phrase)>=12 and len(matches)==1:rects+=matches
        for rect in rects:p.add_highlight_annot(rect)
        return p.get_pixmap(matrix=pymupdf.Matrix(1.2,1.2)).tobytes("png")
