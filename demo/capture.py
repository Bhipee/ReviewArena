"""Capture the local workspaces with an isolated headless browser."""
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':900},device_scale_factor=1)
    page.goto('http://127.0.0.1:8516')
    page.get_by_role('heading',name='ReviewArena',exact=True).wait_for()
    page.get_by_text('Corpus',exact=True).click()
    page.get_by_text('48,581',exact=True).wait_for()
    page.locator('[data-testid=stVegaLiteChart] canvas, [data-testid=stVegaLiteChart] svg').first.wait_for(timeout=30000)
    page.screenshot(path=ROOT/'corpus.png')
    page.get_by_text('Manuscript review',exact=True).click()
    page.get_by_role('combobox',name='Manuscript',exact=True).click()
    page.get_by_text('Efficient Dictionary Learning with Switch Sparse Autoencoders',exact=True).last.click()
    page.get_by_role('button',name='Run three reviewers').wait_for()
    page.screenshot(path=ROOT/'manuscript.png')
    page.get_by_role('radio',name='Rebuttal',exact=True).check()
    if not page.get_by_role('heading',name='Rebuttal workbench').is_visible():
        manuscript=page.get_by_role('combobox',name='Manuscript',exact=True)
        if manuscript.is_visible():
            manuscript.click()
            page.get_by_text('Efficient Dictionary Learning with Switch Sparse Autoencoders',exact=True).last.click()
    page.get_by_role('heading',name='Rebuttal workbench').wait_for()
    page.get_by_text('Use an actual reviewer comment').click()
    page.wait_for_function("document.querySelector('textarea')?.value.length > 30")
    print('Actual review length:',len(page.get_by_role('textbox',name='Paste reviewer comments').input_value()))
    page.screenshot(path=ROOT/'rebuttal.png')
    assert not page.locator('[data-testid="stException"]').count()
    browser.close()
