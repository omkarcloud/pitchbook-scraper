"""HTML / XML -> clean dicts for every /pitchbook/* endpoint. Pure functions, no I/O.

PitchBook serves its public "profile previews" as server-rendered HTML: no
JSON call, no state object. A page is a row of headline numbers, a contact
block and a run of anchored sections (`data-anchor-section`: funding,
competitors, investors, ...), most of them a table of 5 or 10 rows with the
true total in the heading ("Competitors (119)"). The only data inside the
HTML is ld+json, which repeats the name, the logo and the address in parts.

What the site keeps for subscribers is greyed out ON ITS SERVER: the cell
holds `<span class="data-table__gray-box">` and no value. Such a value is
null here, and so is a value the site masks in part (a phone number cut
after its area code, an email after two letters). An empty cell is null as
well: the site prints nothing where it has nothing.

Forms on the page, and what they become:
    28-Jun-2026 / August 3, 2026 / Oct 1, 2026   ->  2026-06-28 (ISO)
    Jun 2014 (an advisor's deal month)           ->  2014-06
    $418K / $9.7B / $3.6T                        ->  418000 / 9700000000 / 3600000000000,
                                                     with `currency` beside it (USD)
    1,470                                        ->  1470
    30. Debt - General (a funding row)           ->  deal_number 30, deal_type "Debt - General"
    In Thousands, USD (the financials table)     ->  whole units

Fixtures (pitchbook/fixtures, raw pages as the site sent them, captured
2026-11-21, packed with gzip): one page per kind of record and per case
(a venture-backed, an acquired, a public and a sparse company; three kinds
of investor; two funds, limited partners and advisors; an industry; two
screeners; search pages; the 404 and 410 pages; the two challenge pages).
The sitemap fixture of company file 75 is cut to its first 200 links.
"""
import html as html_lib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from lxml import html as lxml_html

from pitchbook import refs
from scraper_utils.dates import iso_date as _long_date
from scraper_utils.dates import iso_utc
from scraper_utils.text import lower_snake

SEARCH_PAGE_SIZE = 15          # the site's own search page
SITEMAP_FILE_SIZE = 20000      # links in one sitemap file (the last file of a kind holds fewer)

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿­"))
_GATE_TEXT = "available in the pitchbook platform"
_NO_LOGO = ("/img/", "data:")
_DASHES = ("—", "–", "-", "--", "N/A", "n/a")


# ---- text and values -----------------------------------------------------------------

def _tree(html):
    """The parsed page, with every <br> turned into a space so that a label
    broken over two lines reads as two words."""
    tree = lxml_html.fromstring(html)
    for br in tree.iter("br"):
        br.tail = " " + (br.tail or "")
    return tree


def _text(node):
    """A node's text (or a text) with whitespace collapsed; None when it
    holds none. A `title` attribute of the site can carry an escaped entity
    or a <br> of its own: both are read the way the page shows them."""
    if node is None:
        return None
    text = node if isinstance(node, str) else node.text_content()
    if isinstance(node, str) and ("&" in text or "<" in text):
        text = html_lib.unescape(re.sub(r"<[^>]{1,40}>", " ", text))
    text = re.sub(r"\s+", " ", text.translate(_ZERO_WIDTH)).strip()
    return None if not text or text in _DASHES else text


def _hidden(node):
    """True when the site greyed out (all or part of) this value."""
    return node is not None and bool(node.xpath('.//*[contains(@class, "gray-box")]'))


def _value(node):
    """The text a visitor reads in a cell: its `title` when the cell is cut
    with an ellipsis, else its text. None when greyed out or empty."""
    if node is None or _hidden(node):
        return None
    return _text(node.get("title") or "") or _text(node)


def _int(text):
    """'1,470' -> 1470; anything else -> None."""
    text = _text(text) if text is not None else None
    if not text or not re.fullmatch(r"-?[\d,]+", text):
        return None
    return int(text.replace(",", ""))


_CURRENCIES = {"$": "USD", "US$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR", "₩": "KRW",
               "CA$": "CAD", "C$": "CAD", "A$": "AUD", "AU$": "AUD", "HK$": "HKD", "S$": "SGD", "R$": "BRL",
               "CHF": "CHF", "kr": "SEK"}
_MULTIPLIERS = {"K": 10 ** 3, "M": 10 ** 6, "B": 10 ** 9, "T": 10 ** 12}
_AMOUNT_RE = re.compile(r"(?P<neg>[-(])?\s*(?P<cur>[^\d\s.,()-]{0,4})\s*(?P<num>\d[\d,]*(?:\.\d+)?|\.\d+)\s*"
                        r"(?P<mult>[KMBT])?\s*(?P<unit>[%x])?\)?")


def _amount(text):
    """(number, currency) of '$418K', '€1.2B', '7.43B', '(1,234)', '12.5%',
    '1.8x'. The number is in whole units, an int when it is whole. A text
    that is not a number gives (None, None)."""
    text = _text(text) if text is not None else None
    match = _AMOUNT_RE.fullmatch(text or "")
    if not match:
        return None, None
    try:
        value = Decimal(match.group("num").replace(",", "")) * _MULTIPLIERS.get(match.group("mult"), 1)
    except InvalidOperation:
        return None, None
    if match.group("neg"):
        value = -value
    number = int(value) if value == value.to_integral_value() else float(value)
    symbol = match.group("cur")
    return number, (_CURRENCIES.get(symbol, symbol) if symbol else None)


def _number(text):
    return _amount(text)[0]


_DASHED_DATE_RE = re.compile(r"(\d{1,2})-([A-Za-z]{3,9})-(\d{4})")
_MONTH_YEAR_RE = re.compile(r"([A-Za-z]{3,9})\.? (\d{4})")


def _date(text):
    """The site's date forms -> ISO: '28-Jun-2026' and 'August 3, 2026' ->
    2026-06-28 / 2026-08-03, 'Jun 2014' -> 2014-06, '2014' -> 2014. A text
    in no known form is returned as written, so nothing is lost."""
    text = _text(text) if text is not None else None
    if not text:
        return None
    match = _DASHED_DATE_RE.fullmatch(text)
    if match:
        return _long_date(" ".join(match.groups())) or text
    match = _MONTH_YEAR_RE.fullmatch(text)
    if match:
        for form in ("%b %Y", "%B %Y"):
            try:
                return datetime.strptime(" ".join(match.groups()), form).strftime("%Y-%m")
            except ValueError:
                continue
        return text
    if re.fullmatch(r"\d{4}", text):
        return text
    return _long_date(re.sub(r"^([A-Za-z]+),", r"\1", text)) or text


def _absolute(link):
    """A link of the page as a full link."""
    if not link:
        return None
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("/"):
        return refs.SITE + link
    return link


def _logo(src):
    """An uploaded logo's link; None for the site's placeholder icon."""
    if not src or src.startswith(_NO_LOGO):
        return None
    return _absolute(src)


def _entity(node):
    """{id, type, name, link} of the profile a cell names. A name the site
    prints without a link keeps its name alone; a greyed cell is all null."""
    entity = {"id": None, "type": None, "name": None, "link": None}
    if node is None or _hidden(node):
        return entity
    for href in node.xpath(".//a/@href"):
        found = refs.entity_of_link(href)
        if found:
            entity.update(found)
            break
    entity["name"] = _text(node.get("title") or "") or _text(node)
    return entity


# ---- tables --------------------------------------------------------------------------

# A column's label on the site -> (our key, how its cells are read). A label
# that is not here keeps its own words in snake_case, read as text.
COLUMNS = {
    "company name": ("company", "entity"),
    "investor name": ("investor", "entity"),
    "fund name": ("fund", "entity"),
    "limited partner name": ("limited_partner", "entity"),
    "name": ("name", "entity"),
    "lender": ("lender", "entity"),
    "fund manager": ("fund_manager", "entity"),
    "deal type": ("deal_type", "text"),
    "date": ("date", "date"),
    "amount": ("amount", "money"),
    "raised to date": ("raised_to_date", "money"),
    "post-val": ("post_valuation", "money"),
    "valuation/ebitda": ("valuation_to_ebitda", "number"),
    "debt": ("debt", "money"),
    "employees": ("employees", "int"),
    "total raised": ("total_raised", "money"),
    "last financing date/type": ("last_financing", "text"),
    "last financing amount": ("last_financing_amount", "money"),
    "investor since": ("investor_since", "date"),
    "deal date": ("deal_date", "date"),
    "deal size": ("deal_size", "money"),
    "deal amount": ("deal_amount", "money"),
    "exit date": ("exit_date", "date"),
    "exit size": ("exit_size", "money"),
    "year founded": ("year_founded", "int"),
    "founded": ("year_founded", "int"),
    "patent title": ("title", "text"),
    "first filing date": ("first_filing_date", "date"),
    "technology (cpc)": ("technology_cpc", "text"),
    "citations": ("citations", "int"),
    "vintage": ("vintage", "int"),
    "size": ("size", "money"),
    "fund size": ("fund_size", "money"),
    "dry powder": ("dry_powder", "money"),
    "dry powder %": ("dry_powder_percent", "number"),
    "dpi": ("dpi", "number"),
    "rvpi": ("rvpi", "number"),
    "tvpi": ("tvpi", "number"),
    "irr": ("irr_percent", "number"),
    "with": ("deals_together", "int"),
    "exits": ("exits", "int"),
    "type": ("institution_type", "text"),
    "commitment": ("commitment", "money"),
    "commitment date": ("commitment_date", "date"),
    "as of date": ("as_of_date", "date"),
    "contribution (by all lps)": ("contribution", "money"),
    "distribution (to all lps)": ("distribution", "money"),
    "nav": ("nav", "money"),
    "total fund distr+nav": ("total_distribution_and_nav", "money"),
    "mandate amount": ("mandate_amount", "money"),
    "announced date": ("announced_date", "date"),
    "financing date": ("financing_date", "date"),
    "debt/deal date": ("debt_or_deal_date", "date"),
    "debt/deal amount": ("debt_or_deal_amount", "money"),
    "total shared financings": ("total_shared_financings", "int"),
    "last shared financing": ("last_shared_financing", "date"),
    "stock price": ("stock_price", "money"),
    "previous close": ("previous_close", "money"),
    "market cap": ("market_cap", "money"),
    "market capitalization": ("market_cap", "money"),
    "timeframe": ("timeframe", "date_range"),
    "shares": ("shares", "number"),
    "average volume": ("average_volume", "number"),
    "eps": ("eps", "money"),
    "last post valuation": ("last_post_valuation", "money"),
    "number of investments": ("investments_count", "int"),
    "last investment size": ("last_investment_size", "money"),
    "number of commitments": ("commitments_count", "int"),
    "aum": ("aum", "money"),
    "# of shares authorized": ("shares_authorized", "int"),
    "par value": ("par_value", "money"),
    "dividend rate (%)": ("dividend_rate_percent", "number"),
    "original issue price": ("original_issue_price", "money"),
    "liquidation": ("liquidation", "money"),
    "liquidation pref. multiple": ("liquidation_preference_multiple", "number"),
    "conversion price": ("conversion_price", "money"),
    "% owned": ("percent_owned", "number"),
}


def _label(node):
    """A header's words, lower-cased, without the spaces a line break left
    around a slash ('Valuation/ EBITDA' -> 'valuation/ebitda')."""
    text = _text(node) or ""
    return re.sub(r"\s*/\s*", "/", text).lower()


def _column(label):
    if label in COLUMNS:
        return COLUMNS[label]
    return (lower_snake(label) or "value"), "text"


def _typed(node, kind):
    """One cell read the way its column asks -> (value, currency or None)."""
    if kind == "money":
        return _amount(_value(node))
    if kind == "int":
        return _int(_value(node)), None
    if kind == "number":
        return _number(_value(node)), None
    if kind == "date":
        return _date(_value(node)), None
    return _value(node), None


def _row(pairs, nested=False):
    """[(label, node)] of one record -> an ordered dict. The first entity
    column is the row itself (id, type, name, link); a later one is a nested
    object, and so is the first with `nested` (a commitment is no fund: it
    names one). One `currency` follows the last amount when the row has any."""
    row, currency, money_keys = {}, None, []
    for index, (label, node) in enumerate(pairs):
        key, kind = _column(label)
        if kind == "entity":
            if index == 0 and not nested:
                row.update(_entity(node))
            else:
                row[key] = _entity(node) if not _hidden(node) and _text(node) else None
            continue
        if kind == "date_range":        # '06-Jun-2018 to 10-Jun-2018' -> a start and an end
            start, _, end = (_value(node) or "").partition(" to ")
            row[key + "_start"], row[key + "_end"] = _date(start), _date(end)
            continue
        value, found = _typed(node, kind)
        row[key] = value
        if kind == "money":
            money_keys.append(key)
            currency = currency or found
    if money_keys:
        ordered = {}
        for key, value in row.items():
            ordered[key] = value
            if key == money_keys[-1]:
                ordered["currency"] = currency
        row = ordered
    return row


def _headers(table):
    return [_label(th) for th in table.xpath(".//thead//th")]


def _table(table, nested=False):
    """Every body row of a table as a dict keyed by its column."""
    headers = _headers(table)
    rows = []
    for tr in table.xpath(".//tbody/tr"):
        cells = tr.xpath("./td")
        if cells:
            rows.append(_row(list(zip(headers, cells)), nested))
    return rows


def _section_rows(section, nested=False, table=None):
    """The rows of a section's table: [] when the page has no such section,
    None when the site shows the table's header alone and asks the visitor
    to subscribe (the rows exist, and are kept for subscribers)."""
    if section is None:
        return []
    tables = [table] if table is not None else section.xpath(".//table")
    if not tables:
        return []
    rows = _table(tables[0], nested)
    if not rows and _GATE_TEXT in (section.text_content() or "").lower():
        return None
    return rows


def _heading_count(section, label=None):
    """The total a section's heading names: 'Stripe Competitors (119)' ->
    119, or the count after `label` in any of its lines ('Subsidiaries (19)')."""
    if section is None:
        return None
    for node in section.xpath(".//h2|.//h3|.//p"):
        text = _text(node) or ""
        if label and label.lower() not in text.lower():
            continue
        match = re.search(r"\(([\d,]+)\)\s*$", text)
        if match:
            return int(match.group(1).replace(",", ""))
    if not label:           # no count in a heading: "You’re viewing 10 of 138 ..." under the table
        match = re.search(r"viewing [\d,]+ of ([\d,]+)", section.text_content() or "")
        if match:
            return int(match.group(1).replace(",", ""))
    return None


# ---- the parts every profile page shares ---------------------------------------------

def _ld(tree):
    """Every ld+json object of the page, flattened into one list."""
    found = []
    for node in tree.xpath('//script[@type="application/ld+json"]'):
        try:
            data = json.loads(node.text or "")
        except ValueError:
            continue
        found.extend(data if isinstance(data, list) else [data])
    return [item for item in found if isinstance(item, dict)]


def _ld_of(ld, kind):
    return next((item for item in ld if item.get("@type") == kind), {})


def _sections(tree):
    return {node.get("id"): node for node in tree.xpath("//*[@data-anchor-section][@id]")}


def page_reference(html):
    """(path kind, ref) of the record a page is about, from its canonical
    link: ('company', '54782-29'), ('industry', 'saas'). (None, None) for a
    page that is no profile."""
    match = re.search(r'<link[^>]+rel="canonical"[^>]+href="[^"]*?/profiles/([a-z-]+)/([^"/?#]+)"', html or "")
    return (match.group(1), match.group(2)) if match else (None, None)


def _stats(tree):
    """The headline numbers above a profile: {label in lower case: node}."""
    stats = {}
    for item in tree.xpath("//*[@data-pp-overview-item]"):
        parts = item.xpath(".//li")
        if len(parts) >= 2 and _text(parts[0]):
            stats.setdefault(_text(parts[0]).lower(), parts[1])
    return stats


def _info(tree):
    """The contact block's label -> item. The office is printed twice (once
    per screen width): the first one counts."""
    info = {}
    for item in tree.xpath('//*[contains(@class, "pp-contact-info_item")]'):
        children = [child for child in item if isinstance(child.tag, str)]
        if children and _text(children[0]):
            info.setdefault(_text(children[0]).lower(), children)
    return info


def _info_value(info, label):
    children = info.get(label)
    return _value(children[1]) if children and len(children) > 1 else None


def _info_list(info, label, split=True):
    """A comma-separated value, or one line per child, as a list. `split`
    is False for a label the site prints one line per value: its only value
    may hold a comma of its own ('Movies, Music and Entertainment')."""
    children = info.get(label)
    if not children or len(children) < 2:
        return []
    values = [_value(child) for child in children[1:]]
    values = [value for value in values if value]
    if split and len(values) == 1:
        values = [part.strip() for part in values[0].split(", ") if part.strip()]
    return values


def _info_entity(info, label):
    children = info.get(label)
    if not children or len(children) < 2 or _hidden(children[1]) or not _text(children[1]):
        return None
    return _entity(children[1])


def _info_link(info, label):
    children = info.get(label)
    if not children or len(children) < 2:
        return None
    links = children[1].xpath("./@href|.//a/@href")
    return links[0] if links else None


def _description(tree):
    return _text(next(iter(tree.xpath('//*[contains(@class, "pp-description_text")]')), None))


def _address(info, ld, label="corporate office"):
    """The office as parts. The street, city, region and postcode come from
    the page's ld+json, the country and the full text from the lines the
    visitor reads."""
    children = info.get(label)
    lines = [_value(line) for line in (children[1].xpath(".//li") if children and len(children) > 1 else [])]
    lines = [line for line in lines if line]
    postal = _ld_of(ld, "PostalAddress") if label == "corporate office" or lines else {}
    country = _ld_of(ld, "Country").get("name") or (lines[-1] if len(lines) > 1 else None)
    if not lines and not postal:
        return None
    return {
        "street": _text(postal.get("streetAddress") or "") or (lines[0] if len(lines) > 2 else None),
        "city": _text(postal.get("addressLocality") or ""),
        "region": _text(postal.get("addressRegion") or ""),
        "postal_code": _text(postal.get("postalCode") or ""),
        "country": country,
        "address": ", ".join(lines) or None,
    }


def _phone(info, label="corporate office"):
    """The office phone: the site prints the area code and greys the rest,
    which is null here; a number it prints whole is returned."""
    children = info.get(label)
    for node in (children[2:] if children else []):
        if node.tag == "div":
            return _value(node)
    return None


def _social(tree):
    """{linkedin, twitter, facebook} from the contact block's icons."""
    social = {"linkedin": None, "twitter": None, "facebook": None}
    for block in tree.xpath('//*[contains(@class, "info-item__social")]')[:1]:
        for holder in block.xpath("./div[a/@href]"):
            name = (holder.get("class") or "").split()[0].replace("twitter-x", "twitter")
            link = holder.xpath("./a/@href")[0]
            # a person's profile is printed as linkedin.com/company/linkedin.com/in/<name>: keep the real half
            link = re.sub(r"^https?://(?:www\.)?linkedin\.com/company/(?:https?://)?(?:www\.)?(linkedin\.com/)",
                          r"https://www.\1", link)
            social[lower_snake(name) or name] = link
    return social


def _identity(tree, ld, kind):
    path_kind, ref = page_reference(lxml_html.tostring(tree.xpath("//head")[0], encoding="unicode")) if tree.xpath("//head") else (None, None)
    corporation = _ld_of(ld, "Corporation")
    name = _text(next(iter(tree.xpath("//h1")), None)) or _text(corporation.get("name") or "")
    return {
        "id": ref,
        "type": kind,
        "name": name,
        "link": refs.profile_link(kind, ref) if ref else None,
        "logo": _logo(corporation.get("logo")),
    }


def _articles(section, item_class, title_class=None):
    """The research reports or news stories a section lists."""
    if section is None:
        return []
    out = []
    for link in section.xpath(f'.//a[contains(@class, "{item_class}")]'):
        lines = [_text(p) for p in link.xpath(".//p")]
        lines = [line for line in lines if line]
        image = link.xpath(".//img/@src")
        if item_class == "pp-related-research__item":
            title = _text(next(iter(link.xpath('.//*[contains(@class, "item-title")]')), None))
            released = _text(next(iter(link.xpath('.//*[contains(@class, "item-release")]')), None))
            out.append({"title": title, "link": _absolute(link.get("href")), "date": _date(released),
                        "image": _absolute(image[0]) if image else None})
            continue
        category, _, written = (lines[0] if lines else "").partition("|")
        out.append({
            "title": lines[1] if len(lines) > 1 else None,
            "link": _absolute(link.get("href")),
            "date": _date(written.strip()) if written else None,
            "category": category.strip().title() or None,
            "summary": lines[2] if len(lines) > 2 else None,
            "image": _absolute(image[0]) if image else None,
        })
    return out


def _faqs(section):
    """[{question, answer}]. An answer the site greys a value out of ('The
    current valuation of X is .') is null."""
    if section is None:
        return []
    faqs = []
    for question in section.xpath(".//h3"):
        answer = question.getnext()
        if answer is None or not _text(question):
            continue
        faqs.append({"question": _text(question), "answer": None if _hidden(answer) else _fix_spacing(_text(answer))})
    return faqs


def _fix_spacing(text):
    return re.sub(r"\s+([,.;])", r"\1", text) if text else text


def _faq_answer(section, *words):
    """The answer node of the first question that holds every word."""
    if section is None:
        return None
    for question in section.xpath(".//h3"):
        text = (_text(question) or "").lower()
        if all(word in text for word in words):
            return question.getnext()
    return None


def _faq_entities(section, *words):
    answer = _faq_answer(section, *words)
    if answer is None:
        return []
    out = []
    for link in answer.xpath(".//a[@href]"):
        found = refs.entity_of_link(link.get("href"))
        if found:
            out.append({"id": found["id"], "type": found["type"], "name": _text(link), "link": found["link"]})
    return out


def _cards(section):
    """The cards of a 'top 10' or 'to watch' section: the profile, its logo
    and its labelled values, with the `rank` where the site numbers them."""
    if section is None:
        return []
    cards = []
    for item in section.xpath('.//li[contains(@class, "pp-companies-watch__item")]'):
        name_node = next(iter(item.xpath('.//p[contains(@class, "underline-primary")]')), None)
        rank_node = next(iter(item.xpath('.//*[contains(@class, "pp-companies-watch__rank")]')), None)
        card = {"rank": _int(_text(rank_node) or "")} if rank_node is not None else {}
        card.update(_entity(name_node))
        card["logo"] = _logo(next(iter(item.xpath(".//img/@src")), None))
        labels = item.xpath('./p[contains(@class, "font-weight-bold")][not(contains(@class, "underline-primary"))]')
        card.update(_row([(_label(label), label.getnext()) for label in labels]))
        cards.append(card)
    return cards


def _split_ticker(row):
    """'Microsoft (NAS: MSFT)' -> name Microsoft, stock_exchange NAS,
    stock_symbol MSFT (the public-company tables print them together)."""
    match = re.fullmatch(r"(.+?) \(([A-Z]{2,6}): ([A-Z0-9.\-]+)\)", row.get("name") or "")
    out = {}
    for key, value in row.items():
        out[key] = match.group(1) if (key == "name" and match) else value
        if key == "link":
            out["stock_exchange"] = match.group(2) if match else None
            out["stock_symbol"] = match.group(3) if match else None
    return out


def _contact_fields(tree, info, ld):
    return {
        "website": _info_link(info, "website"),
        "phone": _phone(info),
        "social": _social(tree),
        "office": _address(info, ld),
    }


# ---- companies -----------------------------------------------------------------------

def _funding_rounds(section):
    rows = _section_rows(section)
    for row in rows or []:
        match = re.fullmatch(r"(\d+)\. (.+)", row.get("deal_type") or "")
        number, deal_type = (int(match.group(1)), match.group(2)) if match else (None, row.get("deal_type"))
        ordered = {"deal_number": number, "deal_type": deal_type}
        ordered.update({key: value for key, value in row.items() if key != "deal_type"})
        row.clear()
        row.update(ordered)
    return rows


def _stock(section, info, stats):
    if section is None:
        return None
    table = next(iter(section.xpath(".//table")), None)
    cells = table.xpath(".//tbody/tr[1]/td") if table is not None else []
    values = dict(zip(_headers(table), cells)) if table is not None else {}
    price, currency = _amount(_value(values.get("stock price")))
    low, _, high = (_value(values.get("52 wk range")) or "").partition(" - ")
    as_of = re.search(r"As of (\d{1,2}-[A-Za-z]{3}-\d{4})", section.text_content() or "")
    return {
        "exchange": _info_value(info, "stock exchange"),
        "symbol": _value(stats.get("stock symbol")),
        "price": price,
        "previous_close": _number(_value(values.get("previous close"))),
        "week_52_low": _number(low),
        "week_52_high": _number(high),
        "market_cap": _number(_value(values.get("market cap"))),
        "shares": _number(_value(values.get("shares"))),
        "average_volume": _number(_value(values.get("average volume"))),
        "eps": _number(_value(values.get("eps"))),
        "currency": currency,
        "as_of": _date(as_of.group(1)) if as_of else None,
    }


_UNITS = {"thousands": 10 ** 3, "millions": 10 ** 6, "billions": 10 ** 9}


def _financials(section):
    """The financials summary of a public company: one row per reporting
    period, every figure in whole units of `currency` (the site prints them
    in thousands)."""
    if section is None:
        return None
    table = next(iter(section.xpath(".//table")), None)
    if table is None:
        return None
    heads = table.xpath(".//thead//th")
    unit_text = (_text(heads[0]) or "") if heads else ""
    unit = next((factor for word, factor in _UNITS.items() if word in unit_text.lower()), 1)
    currency = (re.search(r"\b([A-Z]{3})\b", unit_text) or [None, None])[1]
    periods = []
    for head in heads[1:]:
        parts = [_text(span) for span in head.xpath("./span")] or [_text(head)]
        periods.append({"period": parts[0], "period_end": _date(parts[1]) if len(parts) > 1 else None})
    for tr in table.xpath(".//tbody/tr"):
        cells = tr.xpath("./td")
        key = lower_snake(_text(cells[0]) or "") if cells else None
        if not key:
            continue
        for period, cell in zip(periods, cells[1:]):
            figure = _number(_value(cell))
            ratio = "%" in (_text(cells[0]) or "") or "margin" in key or "multiple" in key
            period[key] = figure if figure is None or ratio else figure * unit
    return {"currency": currency, "periods": periods}


def _patents(section):
    if section is None:
        return None
    totals = {}
    for item in section.xpath('.//li[contains(@class, "pp-patents__item")]'):
        name = (_text(next(iter(item.xpath('.//*[contains(@class, "pp-patents__item-name")]')), None)) or "").lower()
        totals[name] = _int(_value(next(iter(item.xpath(".//h3")), None)) or "")
    return {
        "total_documents": totals.get("total documents"),
        "total_families": totals.get("total patents"),
        "granted": totals.get("granted"),
        "pending": totals.get("pending"),
        "expiring_next_12_months": totals.get("expiring"),
        "recent": _section_rows(section) or [],
    }


def _esg(section):
    if section is None:
        return None
    rating = next((_text(h2) for h2 in section.xpath(".//h2") if "|" in (_text(h2) or "")), None)
    score, _, level = (rating or "").partition("|")
    updated = re.search(r"Updated ([A-Za-z]+,? \d{1,2}, \d{4})", section.text_content() or "")

    def greyed_or_text(label):
        for node in section.xpath(f'.//p[normalize-space()="{label}"]'):
            value = next(iter(node.getparent().xpath("./h2")), None)
            return _value(value)
        return None

    peers = []
    for rank_label in section.xpath('.//p[normalize-space()="Rank"]'):
        # <name> / <level> / "<rank> of <companies>" + "Rank" / <percentile> + "Percentile"
        box = rank_label.getparent()
        group = box.getparent().getparent()
        lines = [_text(line) for line in group.xpath("./p")]
        ranked = box.xpath("./p")[0]
        rank = re.fullmatch(r"(?:([\d,]+) )?of ([\d,]+)", _text(ranked) or "")
        percentile = next(iter(group.xpath('.//p[normalize-space()="Percentile"]')), None)
        shown = percentile.getparent() if percentile is not None else None
        value = None if shown is None or _hidden(shown) else _number((_text(shown) or "").replace("Percentile", "").strip())
        peers.append({
            "group": lower_snake(lines[1]) if len(lines) > 1 and lines[1] else None,
            "name": lines[0] if lines else None,
            "rank": _int(rank.group(1)) if rank and rank.group(1) and not _hidden(ranked) else None,
            "companies_count": _int(rank.group(2)) if rank else None,
            "percentile": value,
        })
    return {
        "risk_rating": _number(score.strip()),
        "risk_level": level.strip() or None,
        "exposure": greyed_or_text("Exposure"),
        "management": greyed_or_text("Management"),
        "updated": _date(updated.group(1)) if updated else None,
        "peer_groups": peers,
    }


def _employees_as_of(section):
    """The year of the employee count ('As of 2026'), printed only in the
    comparisons block."""
    if section is None:
        return None
    for cell in section.xpath('(.//*[contains(@class, "comparisons-table__data")])[1]'
                              '//*[contains(@class, "comparisons-table__employees")]'):
        match = re.search(r"As of (\d{4})", _text(cell) or "")
        if match:
            return int(match.group(1))
    return None


def parse_company(html):
    """A company profile page -> the company record."""
    tree = _tree(html)
    ld, stats, info, sections = _ld(tree), _stats(tree), _info(tree), _sections(tree)
    faqs = sections.get("faqs")
    latest_amount, latest_currency = _amount(_value(stats.get("latest deal amount")))
    raised = re.search(r"has raised (\S+?)\.?$", _text(_faq_answer(faqs, "how much funding")) or "")
    total_raised, raised_currency = _amount(raised.group(1)) if raised else (None, None)
    # the word that ends the question, with its mark: the company's own name may hold the word too
    # ('Who are Investors Title’s competitors?', 'When was Acquired Labs founded?')
    acquired = re.search(r"acquired on (\d{1,2}-[A-Za-z]{3}-\d{4})", _text(_faq_answer(faqs, "when was", "acquired?")) or "")
    investors = _section_rows(sections.get("investors"))
    faq_investors = _faq_answer(faqs, "who are", "investors?")
    investors_total = re.search(r"of ([\d,]+) investors", _text(faq_investors) or "")
    named = _faq_entities(faqs, "who are", "investors?")
    if not investors and named:     # the table is kept for subscribers; the FAQ still names up to five of them
        investors = [{**entity, "investor_type": None, "holding": None, "investor_since": None,
                      "participating_rounds": None} for entity in named]
    by_name = {entity["name"]: entity for entity in named}
    for row in investors or []:     # the table prints the names without a link; the FAQ links the same investors
        if not row.get("id") and row.get("name") in by_name:
            row.update(by_name[row["name"]])
    affiliates = sections.get("affiliates")
    return {
        **_identity(tree, ld, "company"),
        "description": _description(tree),
        "status": _value(stats.get("status")),
        "ownership_status": _info_value(info, "ownership status"),
        "financing_status": _info_value(info, "financing status"),
        "year_founded": _int(_value(stats.get("year founded")) or ""),
        "employees": _int(_value(stats.get("employees")) or ""),
        "employees_as_of": _employees_as_of(sections.get("comparisons")),
        "formerly_known_as": _info_list(info, "formerly known as"),
        "primary_industry": _info_value(info, "primary industry"),
        "other_industries": _info_list(info, "other industries", split=False),
        "verticals": _verticals(info),
        "acquirer": _info_entity(info, "acquirer"),
        "acquired_date": _date(acquired.group(1)) if acquired else None,
        "parent_company": _info_entity(info, "parent company"),
        **_contact_fields(tree, info, ld),
        "latest_deal_type": _value(stats.get("latest deal type")),
        "latest_deal_amount": latest_amount,
        "total_raised": total_raised,
        "currency": latest_currency or raised_currency,
        "financing_rounds_count": _int(_value(stats.get("financing rounds")) or ""),
        "investors_count": (_heading_count(sections.get("investors")) or _int(_value(stats.get("investors")) or "")
                            or (int(investors_total.group(1).replace(",", "")) if investors_total else None)),
        "investments_count": _heading_count(sections.get("investments")) or _int(_value(stats.get("investments")) or ""),
        "competitors_count": _heading_count(sections.get("competitors")),
        "exits_count": _heading_count(sections.get("exits")),
        "subsidiaries_count": _heading_count(affiliates, "Subsidiaries"),
        "funding_rounds": _funding_rounds(sections.get("funding")),
        "stock": _stock(sections.get("stock"), info, stats),
        "financials": _financials(sections.get("financials")),
        "cap_table": _section_rows(sections.get("captable")),
        "competitors": _section_rows(sections.get("competitors")),
        "investors": investors,
        "investments": _section_rows(sections.get("investments")),
        "exits": _section_rows(sections.get("exits")),
        "affiliates": _section_rows(affiliates),
        "patents": _patents(sections.get("patents")),
        "esg": _esg(sections.get("esg")),
        "research": _articles(sections.get("research"), "pp-related-research__item"),
        "news": _articles(sections.get("related-news"), "pp-news-about__item"),
        "faqs": _faqs(faqs),
    }


def _verticals(info):
    children = info.get("vertical(s)")
    out = []
    for link in (children[1].xpath(".//a[@href]") if children and len(children) > 1 else []):
        slug = refs.vertical_of_link(link.get("href"))
        if slug:
            out.append({"name": _text(link), "slug": slug, "link": refs.industry_link(slug)})
    return out


# ---- investors -----------------------------------------------------------------------

def parse_investor(html):
    """An investor profile page (a firm, an accelerator or an angel)."""
    tree = _tree(html)
    ld, stats, info, sections = _ld(tree), _stats(tree), _info(tree), _sections(tree)
    return {
        **_identity(tree, ld, "investor"),
        "description": _description(tree),
        "investor_type": _value(stats.get("investor type")),
        "status": _value(stats.get("status")),
        "investor_status": _info_value(info, "investor status"),
        "primary_investor_type": _info_value(info, "primary investor type"),
        "other_investor_types": _info_list(info, "other investor types"),
        "year_founded": _int(_info_value(info, "year founded") or ""),
        "professionals_count": _int(_value(stats.get("professionals")) or ""),
        "formerly_known_as": _info_list(info, "formerly known as"),
        "trade_associations": _info_list(info, "trade association"),
        **_contact_fields(tree, info, ld),
        "investments_count": _int(_value(stats.get("investments")) or "") or _heading_count(sections.get("investments")),
        "portfolio_count": _int(_value(stats.get("portfolio")) or ""),
        "exits_count": _int(_value(stats.get("exits")) or "") or _heading_count(sections.get("exits")),
        "co_investors_count": _heading_count(sections.get("coinvestors")),
        "subsidiaries_count": _heading_count(sections.get("affiliates"), "Subsidiaries"),
        "investments": _section_rows(sections.get("investments")),
        "exits": _section_rows(sections.get("exits")),
        "funds": _section_rows(sections.get("funds")),
        "co_investors": _section_rows(sections.get("coinvestors")),
        "affiliates": _section_rows(sections.get("affiliates")),
        "news": _articles(sections.get("related-news"), "pp-news-about__item"),
        "faqs": _faqs(sections.get("faqs")),
    }


# ---- funds ---------------------------------------------------------------------------

def parse_fund(html):
    """A fund profile page."""
    tree = _tree(html)
    ld, stats, info, sections = _ld(tree), _stats(tree), _info(tree), _sections(tree)
    size, size_currency = _amount(_value(stats.get("size")))
    dry_powder, powder_currency = _amount(_value(stats.get("dry powder")))
    return {
        **_identity(tree, ld, "fund"),
        "description": _description(tree),
        "strategy": _value(stats.get("fund strategy")),
        "status": _value(stats.get("fund status")),
        "category": _info_value(info, "fund category"),
        "family": _info_value(info, "fund family"),
        "vintage": _int(_value(stats.get("vintage")) or ""),
        "open_date": _date(_info_value(info, "open date")),
        "close_date": _date(_info_value(info, "close date")),
        "size": size,
        "dry_powder": dry_powder,
        "currency": size_currency or powder_currency,
        "native_currency": _info_value(info, "native currency"),
        "domiciles": _info_list(info, "fund domiciles"),
        "manager": _info_entity(info, "fund manager"),
        "manager_website": _info_link(info, "fund manager website"),
        "manager_phone": _phone(info, "fund manager's location"),
        "manager_office": _address(info, ld, "fund manager's location"),
        "investments_count": _heading_count(sections.get("investments")),
        "limited_partners_count": _heading_count(sections.get("limited-partners")),
        "benchmark_funds_count": _heading_count(sections.get("benchmark")),
        "investments": _section_rows(sections.get("investments")),
        "limited_partners": _section_rows(sections.get("limited-partners")),
        "returns": _section_rows(sections.get("fund-returns")),
        "benchmark_funds": _section_rows(sections.get("benchmark")),
        "faqs": _faqs(sections.get("faqs")),
    }


# ---- limited partners ----------------------------------------------------------------

def _yes_no(text):
    return {"yes": True, "no": False}.get((text or "").lower())


def parse_limited_partner(html):
    """A limited partner profile page (a pension fund, an insurer, an endowment)."""
    tree = _tree(html)
    ld, stats, info, sections = _ld(tree), _stats(tree), _info(tree), _sections(tree)
    aum, aum_currency = _amount(_value(stats.get("aum")))
    commitment_size, size_currency = _amount(_info_value(info, "commitment size"))
    return {
        **_identity(tree, ld, "limited_partner"),
        "description": _description(tree),
        "institution_type": _value(stats.get("type")) or _info_value(info, "institution type"),
        "year_founded": _int(_value(stats.get("year founded")) or _info_value(info, "year founded") or ""),
        "professionals_count": _int(_value(stats.get("professionals")) or ""),
        "formerly_known_as": _info_list(info, "formerly known as"),
        "aum": aum,
        "commitment_size": commitment_size,
        "currency": aum_currency or size_currency,
        "is_open_to_secondaries": _yes_no(_info_value(info, "open to secondaries")),
        "is_open_to_first_time_funds": _yes_no(_info_value(info, "open to first time funds")),
        "primary_contact": {
            "name": _info_value(info, "primary contact"),
            "title": _info_value(info, "title"),
            "email": _info_value(info, "email"),
            "phone": _info_value(info, "phone"),
        },
        **_contact_fields(tree, info, ld),
        "commitments_count": _int(_value(stats.get("commitments")) or "") or _heading_count(sections.get("commitments")),
        "mandates_count": _heading_count(sections.get("mandates")),
        "subsidiaries_count": _heading_count(sections.get("affiliates"), "Subsidiaries"),
        "commitments": _section_rows(sections.get("commitments"), nested=True),
        "mandates": _section_rows(sections.get("mandates")),
        "affiliates": _section_rows(sections.get("affiliates")),
        "news": _articles(sections.get("related-news"), "pp-news-about__item"),
        "faqs": _faqs(sections.get("faqs")),
    }


# ---- advisors ------------------------------------------------------------------------

def parse_advisor(html):
    """An advisor profile page: a service provider (a law firm, a bank, an
    advisory firm) or a lender."""
    tree = _tree(html)
    ld, stats, info, sections = _ld(tree), _stats(tree), _info(tree), _sections(tree)

    def stat(label):
        return _int(_value(stats.get(label)) or "")

    return {
        **_identity(tree, ld, "advisor"),
        "description": _description(tree),
        "service_type": _value(stats.get("service")) or _info_value(info, "service provider type"),
        "year_founded": _int(_value(stats.get("year founded")) or _info_value(info, "year founded") or ""),
        "employees": stat("employees"),
        "professionals_count": stat("professionals"),
        "formerly_known_as": _info_list(info, "formerly known as"),
        **_contact_fields(tree, info, ld),
        "serviced_companies_count": stat("serviced companies"),
        "serviced_deals_count": stat("serviced deals"),
        "serviced_investors_count": stat("serviced investors"),
        "financed_companies_count": stat("financed companies"),
        "financings_count": stat("financings"),
        "company_services_count": _heading_count(sections.get("companies")),
        "buy_side_services_count": _heading_count(sections.get("buyside")),
        "sell_side_services_count": _heading_count(sections.get("sellside")),
        "co_lenders_count": _heading_count(sections.get("colenders")),
        "company_services": _section_rows(sections.get("companies")),
        "buy_side_services": _section_rows(sections.get("buyside")),
        "sell_side_services": _section_rows(sections.get("sellside")),
        "co_lenders": _section_rows(sections.get("colenders")),
        "investment_preferences": _section_rows(sections.get("preferences")),
        "news": _articles(sections.get("related-news"), "pp-news-about__item"),
        "faqs": _faqs(sections.get("faqs")),
    }


# ---- industries and screeners --------------------------------------------------------

# The headline number's label -> (our key, how it is read).
_LIST_STATS = {
    "companies": ("companies_count", "int"),
    "deals": ("deals_count", "int"),
    "investors": ("investors_count", "int"),
    "exits": ("exits_count", "int"),
    "funds": ("funds_count", "int"),
    "limited partners": ("limited_partners_count", "int"),
    "contacts": ("contacts_count", "int"),
    "largest deal": ("largest_deal", "money"),
    "capital invested": ("capital_invested", "money"),
    "total capital invested (ytd)": ("capital_invested_year_to_date", "money"),
    "median post valuation": ("median_post_valuation", "money"),
}


def _list_stats(stats, keys):
    """The headline numbers of an industry or screener page, every key of
    `keys` present, with one `currency` for the amounts."""
    out, currency = {key: None for key in keys}, None
    for label, node in stats.items():
        key, kind = _LIST_STATS.get(label, (lower_snake(label), "text"))
        value, found = _typed(node, kind)
        out[key] = value
        currency = currency or found
    out["currency"] = currency
    return out


def _slug_identity(tree, html, path_kind, link_of, trim=""):
    _, slug = page_reference(html)
    name = _text(next(iter(tree.xpath("//h1")), None)) or ""
    if trim and name.endswith(trim):
        name = name[:-len(trim)].strip()
    return {"slug": slug, "name": name or None, "link": link_of(slug) if slug else None}


def _split_tables(section):
    """A section that holds several tables -> every table's rows, each list
    under the first header that tells them apart."""
    return [(set(_headers(table)), _table(table)) for table in (section.xpath(".//table") if section is not None else [])]


def parse_industry(html):
    """An industry (vertical) page: its totals, the companies to watch and
    the top companies and investors."""
    tree = _tree(html)
    stats, sections = _stats(tree), _sections(tree)
    private, public = [], []
    for headers, rows in _split_tables(sections.get("top-private-and-public-companies")):
        if "stock price" in headers:
            public = [_split_ticker(row) for row in rows]
        else:
            private = rows
    return {
        **_slug_identity(tree, html, "industry", refs.industry_link, trim="Industry Data"),
        "description": _description(tree),
        **_list_stats(stats, ("companies_count", "deals_count", "investors_count", "exits_count", "largest_deal",
                              "capital_invested", "median_post_valuation")),
        "companies_to_watch": _cards(sections.get("companies-to-watch")),
        "top_private_companies": private,
        "top_public_companies": public,
        "top_investors": _section_rows(sections.get("top-investors-acquirers")),
        "research": _articles(sections.get("research"), "pp-related-research__item"),
        "news": _articles(sections.get("related-news"), "pp-news-about__item"),
        "faqs": _faqs(sections.get("faqs")),
    }


# A screener's section -> our key. A section that is not here is returned
# under its own id in snake_case.
_SCREENER_SECTIONS = {
    "top-investors": "top_investors",
    "top-active-investors": "most_active_investors",
    "top-funds": "top_funds",
    "top-companies": "top_companies",
    "top-private-companies": "top_private_companies",
    "top-public-companies": "top_public_companies",
    "new-companies": "new_companies",
    "recent-deals": "recent_deals",
    "top-lps": "top_limited_partners",
}
_SCREENER_SKIP = {"overview", "description", "research", "related-news", "data", "faqs"}


def parse_screener(html):
    """A screener page (a curated list such as 'angel investors'): its
    totals and every 'top 10' it shows, cards and tables alike."""
    tree = _tree(html)
    stats, sections = _stats(tree), _sections(tree)
    lists = {key: [] for key in _SCREENER_SECTIONS.values()}
    for section_id, section in sections.items():
        if section_id in _SCREENER_SKIP:
            continue
        key = _SCREENER_SECTIONS.get(section_id) or lower_snake(section_id)
        cards = _cards(section)
        rows = cards if cards else (_section_rows(section) or [])
        if key not in lists and not rows:
            continue
        lists[key] = [_split_ticker(row) for row in rows] if key == "top_public_companies" else rows
    return {
        **_slug_identity(tree, html, "screeners", refs.screener_link),
        "description": _description(tree),
        **_list_stats(stats, ("investors_count", "funds_count", "companies_count", "deals_count",
                              "limited_partners_count", "contacts_count", "exits_count", "largest_deal",
                              "capital_invested_year_to_date", "median_post_valuation")),
        **lists,
        "research": _articles(sections.get("research"), "pp-related-research__item"),
        "news": _articles(sections.get("related-news"), "pp-news-about__item"),
        "faqs": _faqs(sections.get("faqs")),
    }


# ---- search --------------------------------------------------------------------------

def parse_search(html):
    """A /profiles/search page -> (rows, total pages). The site publishes no
    result count, only the number of its last page; a page past the end has
    no rows and no page links (total pages None)."""
    tree = _tree(html)
    rows = []
    for link in tree.xpath('//ul[contains(@class, "profile-list")]/li/a[@href]'):
        found = refs.entity_of_link(link.get("href"))
        if not found:
            continue
        name = _text(link.get("title") or "") or _text(next(iter(link.xpath('.//*[contains(@class, "profile-list__title")]')), None))
        rows.append({"id": found["id"], "type": found["type"], "name": name, "link": found["link"],
                     "logo": _logo(next(iter(link.xpath(".//img/@src")), None))})
    pages = [int(number) for number in re.findall(r"[?&]page=(\d+)", " ".join(
        tree.xpath('//div[contains(@class, "pagination")]//a/@href')))]
    total_pages = max(pages) if pages else (1 if rows else None)
    return rows, total_pages


# ---- the sitemap ---------------------------------------------------------------------

_SITEMAP_URL_RE = re.compile(r"<(?:url|sitemap)>\s*<loc>([^<]+)</loc>(?:\s*<lastmod>([^<]+)</lastmod>)?", re.S)


def _sitemap_entries(xml):
    return [(loc.strip(), iso_utc(modified.strip()) if modified else None) for loc, modified in _SITEMAP_URL_RE.findall(xml or "")]


def parse_sitemap_index(xml):
    """The sitemap index -> {file prefix: number of files}, e.g.
    {'company-profiles': 75, 'industry-profiles': 1}."""
    counts = {}
    for loc, _ in _sitemap_entries(xml):
        match = re.search(r"/([a-z-]+)-sitemap-(\d+)\.xml", loc)
        if match:
            counts[match.group(1)] = max(counts.get(match.group(1), 0), int(match.group(2)))
    return counts


def parse_sitemap_profiles(xml):
    """One profile sitemap file -> [{id, type, link, last_modified}]."""
    rows = []
    for loc, modified in _sitemap_entries(xml):
        found = refs.entity_of_link(loc)
        if found:
            rows.append({"id": found["id"], "type": found["type"], "link": found["link"], "last_modified": modified})
    return rows


def parse_sitemap_slugs(xml, path_kind, link_of):
    """The industry or screener sitemap -> [{slug, link, last_modified}]."""
    rows = []
    for loc, modified in _sitemap_entries(xml):
        match = re.search(rf"/profiles/{path_kind}/([^/?#]+)", loc)
        if match:
            rows.append({"slug": match.group(1), "link": link_of(match.group(1)), "last_modified": modified})
    return rows
