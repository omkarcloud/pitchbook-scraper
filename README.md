# 🚀 PitchBook Scraper

PitchBook Scraper is a **free and open-source** scraper that gets you **unlimited** detailed PitchBook data for free.

## ✨ What Can I Get?

- 🏢 **Full profiles of 1.4M+ companies** — funding rounds, investors, competitors, headcount, HQ, website, socials & patents
- 💰 **150K+ funds & 127K+ investors** — fund size, vintage, strategy, managers, portfolios, exits & co-investors
- 🏦 **94K+ advisors & 35K+ limited partners** — law firms and lenders with their deals, plus LP commitments & mandates
- 📊 **59 industries & 173 curated screeners** — market totals, top private & public companies, top investors & recent deals

## 🏢 Example: A Full PitchBook Company

```json
{
  "id": "59199-40",
  "name": "Databricks",
  "link": "https://pitchbook.com/profiles/company/59199-40",
  "description": "Developer of a data analytics platform designed to offer an open and unified environment for the data and artificial intelligence sectors…",
  "status": "Private",
  "financing_status": "Venture Capital-Backed",
  "year_founded": 2013,
  "employees": 14143,
  "primary_industry": "Database Software",
  "website": "http://www.databricks.com",
  "social": { "linkedin": "https://www.linkedin.com/company/databricks", "twitter": "https://twitter.com/databricks" },
  "office": { "city": "San Francisco", "region": "California", "country": "United States" },
  "latest_deal_type": "Later Stage VC",
  "latest_deal_amount": 5000000000,
  "total_raised": 34300000000,
  "currency": "USD",
  "investors_count": 181,
  "competitors_count": 74,
  "funding_rounds": [
    { "deal_number": 19, "deal_type": "Later Stage VC", "date": "2026-08-13", "amount": 5000000000, "currency": "USD", "status": "Completed", "stage": "Generating Revenue" }
  ],
  "investors": [
    { "id": "10014-49", "name": "Blackstone", "investor_type": "PE/Buyout", "holding": "Minority" },
    { "id": "265238-92", "name": "BOND Capital (San Francisco)", "investor_type": "Venture Capital", "holding": "Minority" }
  ],
  "competitors": [
    { "id": "51196-51", "name": "Cloudera", "financing_status": "Private Equity-Backed", "location": "Santa Clara, CA" }
  ],
  "patents": { "total_documents": 302, "granted": 234, "pending": 61 }
}
```

*Trimmed for readability.* You get everything PitchBook shows a signed-out visitor. What it keeps for subscribers, like valuations and most deal sizes, comes back as `null`.

## 🚀 Unlimited Free PitchBook Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/pitchbook-scraper
cd pitchbook-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

Works on your own connection for about 10 profile pages a minute. For more, set a residential proxy in `PITCHBOOK_PROXY`:

```bash
PITCHBOOK_PROXY=http://user:pass@host:port python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/companies/details?company=59199-40"
```

```json
{
  "id": "59199-40",
  "name": "Databricks",
  "link": "https://pitchbook.com/profiles/company/59199-40",
  "status": "Private",
  "financing_status": "Venture Capital-Backed",
  "year_founded": 2013,
  "employees": 14143,
  "primary_industry": "Database Software",
  "website": "http://www.databricks.com",
  "latest_deal_type": "Later Stage VC",
  "latest_deal_amount": 5000000000,
  "total_raised": 34300000000,
  "currency": "USD",
  "investors_count": 181,
  "competitors_count": 74,
  "office": { "city": "San Francisco", "region": "California", "country": "United States" },
  "funding_rounds": [
    { "deal_number": 19, "deal_type": "Later Stage VC", "date": "2026-08-13", "amount": 5000000000, "currency": "USD" }
  ],
  "investors": [
    { "id": "10014-49", "name": "Blackstone", "investor_type": "PE/Buyout" }
  ]
}
```

All 11 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

11 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Company Details | `/companies/details` | The whole company profile in one call · website contacts hosted only |
| Search Profiles | `/profiles/search` | Any company, investor, fund, LP or advisor by name, 15 per page |
| Investor Details | `/investors/details` | A firm's or angel's portfolio and exits · website contacts hosted only |
| Fund Details | `/funds/details` | Size, vintage, strategy, manager and LPs · website contacts hosted only |
| Limited Partner Details | `/limited-partners/details` | Commitments, mandates and affiliates · website contacts hosted only |
| Advisor Details | `/advisors/details` | Law firms and lenders with their deals · website contacts hosted only |
| Industry Details | `/industries/details` | Market totals, companies to watch, top companies and investors |
| Screener Details | `/screeners/details` | Curated top 10s like unicorns, angel investors and recent deals |
| List Profiles | `/profiles/list` | Every profile of one kind, 1.9M+ in all, 1,000 per page |
| Industries | `/industries/list` | All 59 industries PitchBook tracks |
| Screeners | `/screeners/list` | All 173 curated screeners |


## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-pitchbook-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-pitchbook-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-pitchbook-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/companies/details",
    params={"company": "59199-40"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about PitchBook Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/pitchbook-scraper-github-whatsapp)

[![Ask Us by Email about PitchBook Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20PitchBook%20Scraper%20API&body=I%20need%20help%20using%20the%20PitchBook%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/pitchbook-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/pitchbook-scraper)
