import typing
from pathlib import Path

import click
from playwright.sync_api import sync_playwright
from playwright.sync_api._generated import BrowserContext
from retry import retry
# from rich import print

# from . import utils
import utils

get_link_divs_js = '''
    var as = document.querySelectorAll('a')
    as = Array.from(as)
            .filter(function(a) { return a.href !== ''}).filter(function(a){return a.href !== undefined; })
            .map(function(a) {return {'node': a, 'href': a.href, 'is_long': get_url_parts(a.href) }} )
    
    var a_counts = {}
    as.forEach(function(a, i){
        a_counts[a.href] = a_counts[a.href] || []
        a_counts[a.href].push(i)
    })
    
    var a_top_nodes = as.map(function(a, i){ 
        return get_highest_singular_parent(i, as)
    })
'''

js_to_spotcheck = '''
    a_top_nodes.forEach(function(node){
        node.setAttribute('style', 'border: 4px dotted blue !important;')
    })
'''


def get_bounding_box_info(page):
    bounding_boxes = page.evaluate('''    
        function () {
            var all_links = []
            a_top_nodes.forEach(function(node){
                var links = Array.from(node.querySelectorAll('a'))
                if ((links.length == 0) & (node.nodeName === 'A')){
                    links = [node]
                }
                
                var seen_links = {};
                links = links
                    .map(function(a) {return {
                         'href': a.href,
                         'link_text' : get_text_of_node(a), 
                        }
                    } )
                    .sort((a, b) => { return  b.link_text.length - a.link_text.length } )
                    .filter(function(a){
                        if (!(a.href in seen_links)) {
                            seen_links[a.href] = true;
                            return true
                        }
                        return false 
                    })
                    .forEach(function(a){
                        var b = node.getBoundingClientRect() // get the bounding box around the entire defined node.
                        a['x'] = b['x']
                        a['y'] = b['y']
                        a['width'] = b['width']
                        a['height'] = b['height']
                        a['all_text'] = get_text_of_node(node)
                        a['css_attributes'] = getComputedStyle(node)
                        a['img'] = Array.from(a.querySelectorAll('img')).map(function(img){
                            var img_bb = img.getBoundingClientRect()
                            return {
                            'src': img.src, 
                            'alt': img.alt,
                            'x': img_bb['x'],
                            'y': img_bb['y'],
                            'width': img_bb['width'],
                            'height': img_bb['height']
                            }
                        })
                        all_links.push(a)
                })
            })
            
            seen_all_links = {}
            return all_links.filter(function(a){
                if (!([a.href, a.x, a.y] in seen_all_links)) {
                    seen_all_links[[a.href, a.x, a.y]] = true;
                    return true;
                }
                return false;
            })
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


def load_helper_scripts(page):
    """Read and return Javascript code from a file. Convenience function."""
    utils_script = utils.BIN_DIR / "js" / "psl.min.js"
    with open(utils_script ) as f:
        page.evaluate(f.read())

    utils_script = utils.BIN_DIR / "js" / "utils.js"
    with open(utils_script ) as f:
        page.evaluate(f.read())


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
    load_helper_scripts(page)

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
