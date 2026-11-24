"""Use the scraper straight from Python, no server needed.

    python main.py

Each call validates its params with the same schema the API uses (so the
defaults apply) and returns the same JSON the API does, except that a list
keeps its `pagination` block instead of next / previous links. The results
are written to output/*.json.
"""
import json
import os

from pitchbook import api, schemas
from schema_fields import load_query

os.makedirs("output", exist_ok=True)


def run(schema_cls, impl, **params):
    data, error = load_query(schema_cls, {k: str(v) for k, v in params.items()})
    if error:
        raise ValueError(error)
    return impl(**data)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # Databricks' full profile: funding rounds, investors, competitors, HQ, website, socials, headcount and patents
    save("companies_details.json", run(schemas.CompanySchema, api.company_details, company='59199-40'))

    # Every company, investor and fund named "databricks": id, type, name, link and logo (15 per page)
    save("profiles_search.json", run(schemas.ProfilesSearchSchema, api.profiles_search, query='databricks'))

    # Y Combinator's profile: portfolio, exits, recent investments, co-investors, HQ, website and socials
    save("investors_details.json", run(schemas.InvestorSchema, api.investor_details, investor='40420-36'))
