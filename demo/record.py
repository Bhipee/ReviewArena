"""Record the actual local Streamlit/browser session, including verified replay and reveal."""
from pathlib import Path
import os,subprocess,tempfile,sys
import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent
TITLE="Efficient Dictionary Learning with Switch Sparse Autoencoders"
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",str(Path(sys.prefix)/"pw-browsers"))
with tempfile.TemporaryDirectory() as tmp,sync_playwright() as client:
    browser=client.chromium.launch(channel="chrome",headless=True)
    size={"width":1440,"height":900}
    context=browser.new_context(viewport=size,record_video_dir=tmp,record_video_size=size)
    page=context.new_page()
    recording=page.video
    def hold(seconds):
        page.wait_for_timeout(seconds*1000)
    page.goto(os.environ.get("REVIEWARENA_DEMO_URL","http://127.0.0.1:8516"))
    sidebar=page.locator('[data-testid="stSidebar"]')
    sidebar.get_by_text("Manuscript review",exact=True).click()
    sidebar.get_by_role("combobox",name="Manuscript",exact=True).click()
    page.get_by_role("option",name=TITLE,exact=True).click()
    page.get_by_role("heading",name=TITLE,exact=True).wait_for()
    page.locator(".st-key-demo-manuscript-reading button").click()
    page.get_by_text("Claims as stated in the manuscript",exact=True).click()
    page.locator("details[open] img").first.scroll_into_view_if_needed()
    hold(5)
    page.get_by_text("Claims as stated in the manuscript",exact=True).click()
    page.get_by_text("Limitations already stated by the authors",exact=True).click()
    page.locator("details[open] img").first.scroll_into_view_if_needed()
    hold(5)
    page.get_by_text("Limitations already stated by the authors",exact=True).click()
    page.locator(".st-key-demo-manuscript-review button").click()
    page.get_by_text("Area chair recommendation",exact=True).wait_for()
    page.get_by_text("Experiments and evaluation",exact=True).first.scroll_into_view_if_needed()
    hold(4)
    questions=page.get_by_text("Open questions for the authors (",exact=False).first
    if questions.count():
        questions.click()
        page.get_by_role('button',name='Compare question wording with historical reviews').click()
        find=page.get_by_role('button',name='Find figures and tables for these questions')
        if find.count():find.click()
        page.get_by_role('textbox',name='Evidence or revision decision').first.fill(
            'Verify this question against the reported setting before revising the manuscript.')
        page.get_by_role('button',name='Prepare author notes').click()
        with page.expect_download() as notes:
            page.get_by_text('Download prepared author notes',exact=True).click()
        saved=Path(notes.value.path()).read_text()
        if TITLE not in saved or 'Reviewed PDF (SHA-256): ' not in saved:
            raise RuntimeError('Exported revision notes lack the manuscript identity')
        questions.click()
    page.get_by_text("Area chair recommendation",exact=True).scroll_into_view_if_needed()
    hold(6)
    page.get_by_text("Reveal actual reviews and decision",exact=True).click()
    change=page.get_by_text('Did the model-scale evidence change after review?',exact=True)
    change.click()
    page.get_by_text('Later public manuscript',exact=True).click()
    page.get_by_text('We also train on a single layer of Gemma 2 2B (Team et al., 2024).',exact=True).scroll_into_view_if_needed()
    hold(4)
    change.click()
    page.get_by_text("Published mean",exact=True).scroll_into_view_if_needed()
    hold(5)
    sidebar.get_by_text("Rebuttal",exact=True).click()
    page.get_by_role("heading",name="Rebuttal workbench").wait_for()
    page.get_by_text("Use an actual reviewer comment",exact=True).click()
    page.locator(".st-key-demo-rebuttal-reply button").wait_for()
    hold(4)
    page.locator(".st-key-demo-rebuttal-reply button").click()
    page.get_by_text("Experiment checklist",exact=True).wait_for()
    page.get_by_text("Experiment checklist",exact=True).scroll_into_view_if_needed()
    hold(5)
    with page.expect_download() as downloading:
        page.get_by_text("Download Markdown",exact=True).click()
    exported=Path(downloading.value.path()).read_text()
    if '**Response (experiment)**' not in exported:raise RuntimeError("Exported rebuttal did not contain the experimental response")
    if page.locator('[data-testid="stException"]').count():raise RuntimeError("Streamlit exception in recording")
    context.close()
    browser.close()
    out=ROOT/"ReviewArena_replay.mp4"
    temp=ROOT/"ReviewArena_recording.tmp.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),"-v","error","-y","-i",str(recording.path()),"-c:v","libx264","-pix_fmt","yuv420p","-movflags","+faststart",str(temp)],check=True)
    temp.replace(out)
    print("Browser recording:",out.stat().st_size,"bytes")
