"""Check printed-caption provenance on the held-out PDFs and retrieval on the Switch SAE replay."""
import json
from collections import Counter
from io import BytesIO

from PIL import Image, ImageChops

from run import DATA, write
from reviewarena.api import author_questions, author_question_notes
from reviewarena.paper import parse_pdf, highlight
from reviewarena.verifier import find_captions


def main():
    folder = DATA / 'iclr2025'
    manifest = json.loads((folder / 'manifest.json').read_text())
    coverage = []
    case = None
    for entry in manifest:
        paper_id = entry['id']
        content = (folder / (paper_id + '.pdf')).read_bytes()
        paper = parse_pdf(content)
        assert paper['hash'] == entry['sha256'], paper_id
        counts = Counter()
        for caption in paper['captions']:
            page = caption['page']
            assert 1 <= page <= len(paper['pages']), (paper_id, page)
            assert caption['quote'] in paper['pages'][page - 1], (paper_id, caption)
            counts[caption['label'].split()[0]] += 1
        coverage.append(dict(paper_id=paper_id, figures=counts['Figure'], tables=counts['Table']))
        if paper_id == 'k2ZVAzVeMP':
            result = json.loads((DATA / 'eval-product-claim-coverage' / paper_id / 'D.json').read_text())
            assert result['request']['manuscript_sha256'] == paper['hash']
            question = next(q for q in author_questions(paper, result['checked']) if 'sparsity frontier' in q['question'])
            hits, = find_captions(paper, [question['question']])
            match = next(c for c in hits if c['label'] == 'Figure 3' and c['page'] == 6)
            assert 'FLOP-matched' in match['quote'] and 'Width-matched' in match['quote']
            # A page PNG alone also exists when the quote has no visible highlight.
            plain = Image.open(BytesIO(highlight(content, match['page'], ''))).convert('RGB')
            marked = Image.open(BytesIO(highlight(content, match['page'], match['quote']))).convert('RGB')
            highlight_bounds = ImageChops.difference(plain, marked).getbbox()
            assert highlight_bounds, 'The Figure 3 caption was not visibly highlighted'
            assert match['quote'] in author_question_notes([dict(question, captions=hits)])
            case = dict(paper_id=paper_id, manuscript_sha256=paper['hash'], question=question['question'],
                        retrieved=hits, figure_3_rank=hits.index(match) + 1, highlight_pixel_bounds=highlight_bounds)
    assert case
    summary = dict(papers=len(coverage), papers_with_captions=sum(bool(p['figures'] or p['tables']) for p in coverage),
                   figures=sum(p['figures'] for p in coverage), tables=sum(p['tables'] for p in coverage))
    write(DATA / 'metrics/figure-evidence.json', dict(summary=summary, papers=coverage, case=case))
    print(summary, 'Switch SAE Figure 3 rank:', case['figure_3_rank'])


if __name__ == '__main__':
    main()
