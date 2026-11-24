"""Capture the local workspaces with an isolated headless browser."""
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_controls import set_demo_panel, select_example
ROOT=Path(__file__).resolve().parent
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':900},device_scale_factor=1)
    page.goto('http://127.0.0.1:8516')
    select_example(page,'Efficient Dictionary Learning with Switch Sparse Autoencoders')
    set_demo_panel(page,False)
    page.get_by_role('button',name='Run 5 reviewers').wait_for()
    page.screenshot(path=ROOT/'manuscript.png')
    page.get_by_role('radio',name='Rebuttal',exact=True).check()
    page.get_by_role('heading',name='Rebuttal',exact=True).wait_for()
    set_demo_panel(page)
    page.get_by_text('Use an actual reviewer comment').click()
    page.wait_for_function("document.querySelector('textarea')?.value.length > 30")
    print('Actual review length:',len(page.get_by_role('textbox',name='Paste reviewer comments').input_value()))
    set_demo_panel(page,False)
    page.screenshot(path=ROOT/'rebuttal.png')
    assert not page.locator('[data-testid="stException"]').count()
    browser.close()
