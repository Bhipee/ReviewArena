"""Record the four public research-group workflows and a real Markdown download."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import imageio_ffmpeg
from playwright.sync_api import sync_playwright
from browser_controls import set_demo_panel

ROOT=Path(__file__).resolve().parent
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(Path(sys.prefix)/'pw-browsers'))
with tempfile.TemporaryDirectory() as tmp,sync_playwright() as pw:
    browser=pw.chromium.launch(channel='chrome',headless=True)
    size={'width':1440,'height':900}
    context=browser.new_context(viewport=size,record_video_dir=tmp,record_video_size=size)
    page=context.new_page();video=page.video
    page.goto('http://127.0.0.1:8516')
    page.locator('[data-testid="stSidebar"]').get_by_text('Lab meeting',exact=True).click()
    set_demo_panel(page)
    page.get_by_text('Use the public research-group example',exact=True).click()
    def saved(mode):
        if mode!='question':
            label={'related-work-gap':'Related work','reviewer-2':'Reviewer #2','weekly-brief':'Weekly brief'}[mode]
            page.get_by_text(label,exact=True).first.click()
            page.get_by_role('radio',name=label,exact=True).wait_for(state='attached')
        set_demo_panel(page)
        page.locator('.st-key-demo-lab-'+mode+' button').click()
        set_demo_panel(page,False)
        page.get_by_text('Download meeting notes',exact=True).wait_for()
        if page.locator('[data-testid="stException"]').count():raise RuntimeError(mode+' failed')
    saved('question')
    source=page.locator('[data-testid="stExpander"]').filter(has=page.get_by_text('Show original PDF page',exact=True)).first
    source.locator('summary').click()
    source.get_by_text('Show original PDF page',exact=True).click()
    image=source.locator('img').first
    image.wait_for();image.scroll_into_view_if_needed()
    page.wait_for_timeout(3200)
    saved('related-work-gap')
    links=page.locator('a[href^="https://doi.org/"]')
    links.first.wait_for();assert links.count()==3
    links.first.scroll_into_view_if_needed();page.wait_for_timeout(3500)
    saved('reviewer-2')
    page.get_by_role('heading',name='Contributions',exact=True).scroll_into_view_if_needed()
    page.get_by_role('heading',name='Questions for the author',exact=True).wait_for()
    page.wait_for_timeout(3500)
    saved('weekly-brief')
    page.get_by_role('heading',name='Supervisor questions',exact=True).scroll_into_view_if_needed()
    with page.expect_download() as file:
        page.get_by_text('Download meeting notes',exact=True).click()
    out=Path(tmp)/'meeting.md';file.value.save_as(out)
    assert all('## '+section in out.read_text() for section in ('Completed work','Open questions','Proposed next steps','Supervisor questions'))
    assert 'group-evaluation-note.md, p. 1' in out.read_text()
    assert 'Did the other 9 answers cite an alternative passage' in out.read_text()
    assert 'human citation audit' in out.read_text()

    page.wait_for_timeout(3000)
    context.close();browser.close()
    output=ROOT/'ScholarMate_replay.mp4';temp=ROOT/'ScholarMate_recording.tmp.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-y','-i',str(video.path()),'-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(temp)],check=True)
    temp.replace(output)
    print('Saved lab recording',output.stat().st_size,'bytes',flush=True)
