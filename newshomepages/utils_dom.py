"""Utils specifically for traversing the DOM with playwright"""
from playwright.sync_api import Locator, Page
from playwright_dompath.dompath_sync import css_path, xpath_path
from typing import List, Dict, Union
from urllib.parse import urlparse, ParseResult
import tldextract
import re
from collections import defaultdict
from more_itertools import unique_everseen

DOMAIN_BLACKLIST = [
    "google",
    "twitter",
    "facebook",
    "doubleclick",
    "eventbrite",
    "youtube",
    "vimeo",
    "instagram",
    "ceros"
]

SUBDOMAIN_BLACKLIST = [
    "careers",
    "mail",
    "account",
    "events",
]


def get_parents(node: Locator) -> List[Locator]:
    """Given a child element in the DOM, return the path from ROOT to the child."""
    all_parents = []
    p = [node]
    while len(p) != 0: # this is the cue for the top-most node
        p = p[0]
        all_parents.append(p)
        p = p.locator('xpath=..').all()
    return all_parents[::-1]


def nodes_are_equal(node_1: Locator, node_2: Locator) -> bool:
    """
    Check if two nodes are equal, by checking XPath.
    """
    node_1_xpath = xpath_path(node_1)
    node_2_xpath = xpath_path(node_2)
    return node_1_xpath == node_2_xpath


def get_common_parent(node_1: Locator, node_2: Locator, return_common: bool = True) -> Locator:
    """Given two nodes in the DOM, return the common parent between them.
        * node_1: the target node
        * node_2: the comparator node
        * return_common (bool):
            * if true, return the first node that they both share.
            * if false, return the first node BEFORE the shared node, in the target node.
    """
    parents_1 = get_parents(node_1)
    parents_2 = get_parents(node_2)

    if not nodes_are_equal(parents_1[0], parents_2[0]):
        raise "No common ancestor!"

    for i in range(len(parents_1)):
        if not nodes_are_equal(parents_1[i], parents_2[i]):
            if return_common:
                return parents_1[i - 1]
            else:
                return parents_1[i]


def is_smaller_child(child_candidate: Locator, parent_candidate: Locator) -> bool:
    """Given two nodes (in the same hierarchy), return:
        true if the "child_candidate" is a child of the "parent_candidate",
        false otherwise."""

    child_parents = get_parents(child_candidate)
    parent_candidate = get_parents(parent_candidate)
    return len(child_parents) > len(parent_candidate)


def get_href(a: Locator) -> str:
    return a.evaluate('a => a.href')


def get_highest_singular_parent(i: int, a_links: List[Locator]) -> Locator:
    """
    Get the largest possible bounding box in the DOM hierarchy that doesn't have any other links.

    params:
        * i: the index of node "a" in "a_links"
        * as: an Array of all DOM elements of type "A"
        * a_counts: a mapper from each href => [idx of nodes in as] containing that link.
    """
    a = a_links[i]
    curr_parent = get_parents(a)[0]
    for j in range(len(a_links)):
        if (i != j) and (get_href(a_links[i]) != get_href(a_links[j])):
            common_not_parent = get_common_parent(a, a_links[j], return_common=False)
            if is_smaller_child(common_not_parent, curr_parent):
                curr_parent = common_not_parent
    return curr_parent


def get_text_of_node(node: Locator) -> str:
    return node.evaluate("""node => {
        var iter = document.createNodeIterator(node, NodeFilter.SHOW_TEXT)
        var textnode;
        var output_text = ''
    
        // print all text nodes
        while (textnode = iter.nextNode()) {
          output_text = output_text + ' ' + textnode.textContent
        }
        return output_text.trim()
    }""")


def is_banned_host(url: ParseResult) -> bool:
    host = url.netloc
    domain_parse = tldextract.extract(host)
    if domain_parse.domain not in DOMAIN_BLACKLIST:
        return True

    subdomain = domain_parse.subdomain.replace('www.', '')
    if subdomain not in SUBDOMAIN_BLACKLIST:
        return True

    return False


def get_valid_url(href: str, hostname: str =None):
    """Constructs a URL class out of a href. Flexible in case the href is just the path."""
    url = urlparse(href)
    if url.netloc == '':
        url = urlparse(hostname + href)

    return url


def get_url_parts(href: str, hostname: str = None):
    url = get_valid_url(href, hostname)
    if is_banned_host(url):
        return False

    path = url.path
    path_parts = re.split('[-/:.]', path)
    path_parts = list(filter(lambda x: x != '', path_parts))
    return len(path_parts) > 5


def get_top_divs_from_page(page: Page):
    """Extract all `<a>` tags and follow them up the DOM tree to get the highest link.

    page: Playwright object representing the page.
    """
    all_as = page.locator('a').all()

    # filter out <a> tags without a href
    all_as = list(filter(lambda x: get_href(x) is not None, all_as))

    # count number of unique href links (sometimes an article link and a picture point to the same place)
    a_counts = defaultdict(list)
    for a in all_as:
        href = get_href(a)
        a_counts[href].append(href)

    a_top_nodes = []
    for i, _ in enumerate(all_as):
        highest_parent = get_highest_singular_parent(i, all_as)
        a_top_nodes.append(highest_parent)
    return a_top_nodes


def get_node_name(loc: Locator) -> str:
    return loc.evaluate('e => e.nodeName')


def get_css_attrs(node: Locator) -> Dict[str, str]:
    css_attrs = node.evaluate('''node => getComputedStyle(node)''')
    return dict(filter(lambda x: not x[0].isdigit(), css_attrs.items()))


def get_img_attrs(node: Locator) -> List[Dict[str, Union[str, int]]]:
    output_img_data = []
    imgs = node.locator('img').all()
    for img in imgs:
        output = {}
        bb_img = img.boundingBox()
        output['img_x'] = bb_img['x']
        output['img_y'] = bb_img['y']
        output['img_width'] = bb_img['width']
        output['img_height'] = bb_img['height']
        output['img_src'] = img.evaluate('''node => node.src''')
        output['img_text'] = img.evaluate('''node=> node.alt.trim()''')
        output_img_data.append(output)
    return output_img_data


def get_bounding_box_info(page: Page) -> List[Dict[str, Union[str, int]]]:
    """
    Takes in a page and extracts key information about parts of the page. Key information includes:
        * Bounding boxes for all upper-divs encircling links
        * Images (if any) in the same upper-divs as links
        * Text content associated with any links.

    :param page:
    :return:
    """

    # get page width and page height
    page_width = page.evaluate('''
        Math.max(
            document.documentElement["clientWidth"],
            document.body["scrollWidth"],
            document.documentElement["scrollWidth"],
            document.body["offsetWidth"],
            document.documentElement["offsetWidth"]
        );
    ''')

    page_height = page.evaluate('''Math.max(
        document.documentElement["clientHeight"],
        document.body["scrollHeight"],
        document.documentElement["scrollHeight"],
        document.body["offsetHeight"],
        document.documentElement["offsetHeight"]
    );''')

    # process for each link
    all_links = []
    top_nodes_of_links = get_top_divs_from_page(page)
    for node in top_nodes_of_links:
        # general data
        node_text = get_text_of_node(node)
        css_attrs = get_css_attrs(node)

        # get links and filter to a set of conditions
        links = node.locator('a').all()
        if (len(links) == 0) and (get_node_name(node) == 'A'):
            links = [node]
        links = sorted(links, key=lambda x: -len(get_text_of_node(x)))  # links with the most text first
        links = list(unique_everseen(links, key=lambda x: get_href(x)))
        # iterate through links and get information
        for a in links:
            output = {}
            bb = a.boundingBox()
            output['x'] = bb['x']
            output['y'] = bb['y']
            output['width'] = bb['width']
            output['height'] = bb['height']
            output['page_width'] = page_width
            output['page_height'] = page_height
            output['href'] = get_href(a)
            output['link_text'] = get_text_of_node(a)
            output['all_text'] = node_text
            output['css_attributes'] = css_attrs
            output['img'] = get_img_attrs(a)
            all_links.append(output)

    deduplicated = unique_everseen(all_links, key=lambda x: (x['href'], x['x'], x['y']))
    return list(deduplicated)


def spotcheck_draw_bounding_box(loc: Locator) -> None:
    """To spotcheck, draw bounding boxes on the page. Only useful if you're not in headless mode."""
    loc.evaluate("node => node.setAttribute('style', 'border: 4px dotted blue !important;')"),
