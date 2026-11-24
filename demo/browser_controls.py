"""Select the public paper and open the presenter panel in browser recordings."""


def set_demo_panel(page, opened=True):
    panel = page.locator(".st-key-demo-panel")
    details = panel.locator("details").first
    summary = details.locator("> summary")
    summary.wait_for()
    if details.evaluate("(node) => node.open") != opened:
        summary.click()
    return panel


def select_example(page, title):
    panel = set_demo_panel(page)
    panel.get_by_role("button", name="Use Switch SAE example").click()
    page.get_by_role("heading", name=title, exact=True).wait_for()
