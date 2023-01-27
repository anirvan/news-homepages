import typing
from pathlib import Path

import click
from playwright.sync_api import sync_playwright
from playwright.sync_api._generated import BrowserContext
from retry import retry
from rich import print

from . import utils


instantiate_model_js = '''
    var predictor = new LRUrlPredictor(%s)
'''

instantiate_heuristic_js = '''
    var predictor = new HueristicUrlPredictor()
'''

get_link_divs_js = '''
    var as = document.querySelectorAll('a')
    as = Array.from(as).filter(function(a) { return a.href !== ''}).filter(function(a){return a.href !== undefined; })
    
    // predict whether the URL is an article URL are not 
    as = as.filter(function(a){return predictor.get_prediction(a.href)})
    
    var a_counts = {}
    as.forEach(function(a, i){
        a_counts[a.href] = a_counts[a.href] || []
        a_counts[a.href].push(i)
    })
    
    var a_top_nodes = as.map(function(a, i){ 
        return get_highest_singular_parent(i, as, a_counts) 
    })
'''

js_to_spotcheck = '''
    a_top_nodes.forEach(function(node){
        node.setAttribute('style', 'border: 4px dotted blue !important;')
    })
'''


# await page.evaluate('const lr = new LRPathPredictor(%s)' % lr_obj)#
# t = "https://abcnews.go.com/US/42-magnitude-earthquake-strikes-malibu/story?id=96655478"
# await page.evaluate('lr.get_predictions("%s")' % t)
# >>> True
# t = "https://abcnews.go.com/US/gunviolence"
# await page.evaluate('lr.get_predictions("%s")' % t)
# >>> False


def get_bounding_box_info(page):
    bounding_boxes = page.evaluate('''
        function () {
            var all_links = []
            a_top_nodes.forEach(function(node){
                var links = Array.from(node.querySelectorAll('a')).map(function(a){ return a })
                if ((links.length == 0) & (node.nodeName === 'A')){
                    links = [node]
                }
                links = links.map(function(a){return {'url': a.href, 'link_text': get_text_of_node(a)}})

                links.forEach(function(a){
                    var b = node.getBoundingClientRect()
                    a['x'] = b['x']
                    a['y'] = b['y']
                    a['width'] = b['width']
                    a['height'] = b['height']
                    a['all_text'] = get_text_of_node(node)
                    all_links.push(a)
                })
            })
            return all_links
        }
    ''')

    width = page.evaluate('''
        Math.max(
            document.documentElement["clientWidth"],
            document.body["scrollWidth"],
            document.documentElement["scrollWidth"],
            document.body["offsetWidth"],
            document.documentElement["offsetWidth"]
        );
    ''')

    height = page.evaluate('''Math.max(
        document.documentElement["clientHeight"],
        document.body["scrollHeight"],
        document.documentElement["scrollHeight"],
        document.body["offsetHeight"],
        document.documentElement["offsetHeight"]
    );''')

    return bounding_boxes, width, height


def load_model_files_and_helper_scripts(page):
    """Read and return Javascript code from a file. Convenience function."""
    model_utils_script = utils.BIN_DIR / "js" / "model_utils.js"
    with open(model_utils_script) as f:
        page.evaluate(f.read())

    utils_script = utils.BIN_DIR / "js" / "utils.js"
    with open(utils_script ) as f:
        page.evaluate(f.read())

    model_weights = utils.BIN_DIR / 'model_files' / 'trained_lr_obj.json'
    with open(model_weights) as f:
        return f.read()


@click.command()
@click.argument("handle")
@click.option("-o", "--output-dir", "output_dir", default="./")
@click.option("--timeout", "timeout", default="180")
def cli(handle: str, output_dir: str, timeout: str = "180"):
    """Save all hyperlinks as JSON for a site or bundle."""
    # Get the site
    site = utils.get_site(handle)

    # Start the browser
    with sync_playwright() as p:
        # Open a browser
        browser = p.chromium.launch(channel="chrome")
        context = browser.new_context(user_agent=utils.get_user_agent())

        # Get lnks
        link_list = _get_links(context, site, timeout=int(timeout))

        # Close the browser
        context.close()

    # Write out the data
    output_path = Path(output_dir) / f"{site['handle'].lower()}.hyperlinks-with-bb.json"
    utils.write_json(link_list, output_path)


@retry(tries=3, delay=5, backoff=2)
def _get_links(context: BrowserContext, data: typing.Dict, timeout: int = 180):
    print(f"Getting hyperlinks from {data['url']}")
    # Open a page
    page = context.new_page()

    # Go to the page
    page.goto(data["url"], timeout=timeout * 1000)

    # load helper scripts into the page and get resources to run the rest of the scripts
    model_obj = load_model_files_and_helper_scripts(page)

    # load predictors that will give us bounding boxes for article links on the page.
    # if the language is english, we can predict whether the links on the page are articles or not with
    # slightly higher accuracy than the heuristic, which is just to predict, basically, the length of the URL.
    if data['language'] == 'en':
        page.evaluate(instantiate_model_js % model_obj)
    else:
        page.evaluate(instantiate_heuristic_js)

    # for each <a> on the page, get the upper-most child in the DOM that doesn't have any other links in the subtree
    page.evaluate(get_link_divs_js)

    # retrieve this data from the page object
    bb, w, h = get_bounding_box_info(page)

    # Close the page
    page.close()

    # Return the result
    return {'bounding boxes': bb, 'page_width': w, 'page_height': h}


if __name__ == "__main__":
    cli()
