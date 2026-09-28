"""GDIT Algolia collector, matching the existing V1A JobPosting contract.

The public search parameters were observed on GDIT's career search page on
2026-09-27. Search credentials are public browser search credentials, never
personal account credentials. Override them with environment variables if
GDIT rotates them.
"""
from pathlib import Path
from urllib.parse import urljoin
import csv
import importlib.util
import json
import os
import re
import time

import certifi
import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "source_codes"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
BASE_URL = "https://www.gdit.com"
ALGOLIA_APP = os.environ.get("GDIT_ALGOLIA_APP_ID", "9UXTN7C0A2")
ALGOLIA_KEY = os.environ.get("GDIT_ALGOLIA_SEARCH_KEY", "93d76a4907a0804b16d09213d48d0085")
SEARCH_URL = f"https://{ALGOLIA_APP.lower()}-dsn.algolia.net/1/indexes/*/queries"
TIMEOUT = 30
DELAY = 0.15
MAX_PAGES_PER_TERM = 30
TARGET_REQ = "RQ227420"
TARGET_URL = "/careers/job/1d6d2732b/data-scientist-principal/"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


JobPosting = load_module("gdit_job_schema", SOURCE_DIR / "_job_search_v1A_001_schema_job_posting.py").JobPosting
get_global_search_terms = load_module(
    "gdit_search_terms", SOURCE_DIR / "_job_search_v1A_008_config_search_terms.py"
).get_global_search_terms


def clean(value):
    return " ".join(str(value or "").split())


def make_session():
    session = requests.Session()
    session.verify = certifi.where()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    return session


def search_page(session, term, page):
    payload = {"requests": [{
        "indexName": "gdit", "query": term, "page": page, "hitsPerPage": 10,
        "filters": "NOT deleted:true",
        "facetFilters": ["category:careers", ["visibility:Production"]],
    }]}
    response = session.post(
        SEARCH_URL, headers={"x-algolia-application-id": ALGOLIA_APP,
                             "x-algolia-api-key": ALGOLIA_KEY},
        json=payload, timeout=TIMEOUT,
    )
    response.raise_for_status()
    result = response.json()["results"][0]
    for key in ("hits", "nbHits", "nbPages", "page"):
        if key not in result:
            raise ValueError(f"GDIT search response missing {key}")
    if result["page"] != page:
        raise ValueError(f"GDIT page mismatch: requested {page}, got {result['page']}")
    return result


def normalize_hit(hit):
    req = clean(hit.get("jdtidUniqueNumber"))
    title = clean(hit.get("title"))
    relative_url = hit.get("url") or ""
    if not re.fullmatch(r"RQ\d+", req) or not title or not relative_url.startswith("/careers/job/"):
        raise ValueError(f"Invalid GDIT hit: {req!r}, {title!r}, {relative_url!r}")
    place = ", ".join(filter(None, [clean(hit.get("primaryLocationCity")),
                                     clean(hit.get("primaryLocationState"))]))
    if hit.get("telecommutingOptions") == "Remote" or hit.get("filterLocation") == "Home Office":
        place = "Remote, United States" if not place else f"Remote, {place}"
    # GDIT's Algolia record spells this field "Posses" (one final s).
    clearance = clean(hit.get("clearanceLevelCurrentlyPosses")) or "Unknown"
    return JobPosting(
        job_id=req, company_id="gdit", company_name="GDIT", title=title,
        location=place, description=clean(hit.get("content")),
        apply_url=urljoin(BASE_URL, relative_url),
        posted_date=(clean(hit.get("createdAt"))[:10] or None),
        employment_type=clean(hit.get("jobStatus")) or None,
        clearance=clearance, source="gdit_careers_algolia",
    )


def detail_public_trust(session, job):
    """GDIT detail HTML owns Public Trust; search hit only owns clearance level."""
    response = session.get(job.apply_url, timeout=TIMEOUT)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    # Match the structured h5 label, not the narrative paragraph that also
    # contains the phrase "Public Trust:" and would swallow the whole page.
    for label in soup.select("h5"):
        strong = label.find("strong")
        if strong and clean(strong.get_text(" ", strip=True)).casefold() == "public trust:":
            value = clean(label.get_text(" ", strip=True).split(":", 1)[1])
            if value:
                job.clearance = f"{job.clearance}; Public Trust: {value}"
                return job
    raise ValueError(f"GDIT detail missing Public Trust field: {job.apply_url}")


def collect_jobs():
    terms = get_global_search_terms()
    if not terms:
        raise ValueError("Global search terms are empty")
    session = make_session()
    unique = {}
    raw = requests_count = 0
    print(f"GDIT LIVE COLLECTOR | terms={len(terms)} | max_pages={MAX_PAGES_PER_TERM}")
    for number, term in enumerate(terms, 1):
        page = 0
        while True:
            result = search_page(session, term, page)
            requests_count += 1
            if result["nbPages"] > MAX_PAGES_PER_TERM:
                raise RuntimeError(f"GDIT '{term}' has {result['nbPages']} pages; cap would truncate")
            hits = result["hits"]
            raw += len(hits)
            for hit in hits:
                job = normalize_hit(hit)
                unique.setdefault(job.job_id, job)
            print(f"TERM {number:02d}/{len(terms):02d} {term!r} page={page} hits={len(hits)} total={result['nbHits']}")
            if page + 1 >= result["nbPages"]:
                break
            page += 1
            time.sleep(DELAY)
        time.sleep(DELAY)
    if TARGET_REQ not in unique:
        raise RuntimeError(f"GDIT acceptance failure: {TARGET_REQ} missing from global searches")
    target = unique[TARGET_REQ]
    if not target.apply_url.endswith(TARGET_URL):
        raise RuntimeError(f"GDIT acceptance failure: {TARGET_REQ} URL changed: {target.apply_url}")
    detail_public_trust(session, target)
    requests_count += 1
    if target.clearance != "None; Public Trust: NACI (T1)":
        raise RuntimeError(f"GDIT acceptance failure: {TARGET_REQ} Public Trust not verified: {target.clearance}")
    jobs = sorted(unique.values(), key=lambda j: (j.title.casefold(), j.job_id))
    return jobs, raw, requests_count


def save_outputs(jobs):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = [job.to_dict() for job in jobs]
    json_path, csv_path = OUTPUT_DIR / "gdit_jobs.json", OUTPUT_DIR / "gdit_jobs.csv"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return json_path, csv_path


def main():
    jobs, raw, count = collect_jobs()
    json_path, csv_path = save_outputs(jobs)
    target = next(job for job in jobs if job.job_id == TARGET_REQ)
    print(f"GDIT CLOSED PASS | requests={count} raw={raw} unique={len(jobs)}")
    print(f"TARGET {target.job_id} | {target.title} | {target.clearance} | {target.apply_url}")
    print(f"OUTPUT {json_path} | {csv_path}")


if __name__ == "__main__":
    main()
