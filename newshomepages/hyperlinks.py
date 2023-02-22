import typing
from pathlib import Path

import click
from playwright.sync_api import sync_playwright
from playwright.sync_api import ElementHandle
from playwright.sync_api._generated import BrowserContext
from retry import retry
from rich import print
from typing import List, Union, Dict

from . import utils

get_link_divs_js = '''
    var as = document.querySelectorAll('a')
    as = Array.from(as)
            .filter(function(a) { return a.href !== ''}).filter(function(a){return a.href !== undefined; })
            .map(function(a) {return {'node': a, 'href': a.href, 'is_long': get_url_parts(a.href) }} )
    //
    var a_counts = {}
    as.forEach(function(a, i){
        a_counts[a.href] = a_counts[a.href] || []
        a_counts[a.href].push(i)
    })
    //
    var a_top_nodes = as.map(function(a, i){
        return get_highest_singular_parent(i, as)
    })
'''


def load_helper_scripts(page):
    """Read and return Javascript code from a file. Convenience function."""
    utils_script = utils.BIN_DIR / "js" / "psl.min.js"
    with open(utils_script) as f:
        page.evaluate(f.read())

    utils_script = utils.BIN_DIR / "js" / "utils.js"
    with open(utils_script) as f:
        page.evaluate(f.read())


def get_css_attrs(node: ElementHandle) -> Dict[str, str]:
    """Get all CSS attributes for an article bounding box."""
    css_attrs = node.evaluate('''node => getComputedStyle(node)''')
    return dict(filter(lambda x: not x[0].isdigit(), css_attrs.items()))


def get_img_attrs(node: ElementHandle) -> List[Dict[str, Union[str, int, float]]]:
    """Get bounding boxes and other attributes for all the images in the article bounding box."""
    output_img_data = []
    imgs = node.query_selector_all('img')
    for img in imgs:
        output = {}
        bb = img.bounding_box()
        output['img_position'] = {k: float(v) for k, v in bb.items()}
        output['img_src'] = img.evaluate('''node => node.src''')
        output['img_text'] = img.evaluate('''node=> node.alt.trim()''')
        output_img_data.append(output)
    return output_img_data


def get_bounding_boxes_fallback(page):
    """Get bounding boxes using a two-tiered approach.

    Attempts to get more exact coordinates using javascript, and if this doesn't work (e.g. if some websites use an
    outdated javascript, or something) then use a Playwright-based approach that is slower and less-precise.
    """
    bounding_box_output = []
    all_as = page.query_selector_all('a')
    for a in all_as:
        output = {}
        try:
            output['position'] = a.bounding_box()
        except Exception:
            output['position'] = 'fallback method failed'
        try:
            output['href'] = a.evaluate('a => a.href')
        except Exception:
            output['href'] = 'fallback method failed'
        try:
            output['img'] = get_img_attrs(a)
        except Exception:
            output['img'] = 'fallback method failed'
        try:
            output['css'] = get_css_attrs(a)
        except Exception:
            output['css'] = 'fallback method failed'
        try:
            output['text'] = a.evaluate('a => get_text_of_node(a)')
        except Exception:
            output['text'] = 'fallback method failed'
        bounding_box_output.append(output)
    return bounding_box_output


@click.command()
@click.argument("handle")
@click.option("-o", "--output-dir", "output_dir", default="./")
@click.option("--timeout", "timeout", default="180")
@click.option("--fallback", "use_playwright", is_flag=True,
              help="Flag to automatically use the fallback mechanism for collecting bounding boxes. "
                   "If true, get bounding boxes and related article information using Playwright functionality."
                   "We suspect it is more reliable across sites, generally, but native JS "
                   "(faster, more precise, possibly less relaible). If False, .")
def cli(handle: str, output_dir: str, timeout: str = "180", use_playwright: bool = False):
    """Save all hyperlinks as JSON for a site or bundle."""
    # Get the site
    site = utils.get_site(handle)

    # Start the browser
    with sync_playwright() as p:
        # Open a browser
        browser = p.chromium.launch(channel="chrome")
        context = browser.new_context(user_agent=utils.get_user_agent())

        # Get links
        link_list = _get_links(context, site, timeout=int(timeout), use_playwright=use_playwright)

        # Close the browser
        context.close()

    # Write out the data
    output_path = Path(output_dir) / f"{site['handle'].lower()}.hyperlinks.json"
    utils.write_json(link_list, output_path)


@retry(tries=3, delay=5, backoff=2)
def _get_links(context: BrowserContext, data: typing.Dict, timeout: int = 180, use_playwright: bool = False):
    print(f"Getting hyperlinks from {data['url']}")
    # Open a page
    page = context.new_page()

    # Go to the page
    page.goto(data["url"], timeout=timeout * 1000)

    print('done loading...')
    # load helper scripts into the page and get resources to run the rest of the scripts
    load_helper_scripts(page)

    # retrieve this data from the page object
    js_worked = True
    if not use_playwright:
        try:
            # for each <a> on the page, get the upper-most child in the DOM that doesn't have any other links in the subtree
            page.evaluate(get_link_divs_js)
            # get bounding boxes and other information for all links on the page
            bounding_boxes = page.evaluate('''get_bounding_boxes_for_links_on_page(a_top_nodes)''')
            method = 'full bounding boxes (method succeeded)'
        except Exception:
            js_worked = False

    if use_playwright or (not js_worked):
        print('falling back to playwright to get bounding boxes...')
        bounding_boxes = get_bounding_boxes_fallback(page)
        method = 'a-restricted bounding boxes (fallback method)'

    page_width = page.evaluate('''get_page_width()''')
    page_height = page.evaluate('''get_page_height()''')

    # Close the page
    page.close()

    # Return the result
    return {
        'link data': bounding_boxes,
        'page_width': page_width,
        'page_height': page_height,
        'bounding box method': method
    }


if __name__ == "__main__":
    cli()
