import csv
import importlib.util
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import certifi
import requests
from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "source_codes"
OUTPUT_DIR = PROJECT_ROOT / "outputs"

BASE_URL = "https://www.capitalonecareers.com"
SEARCH_URL = f"{BASE_URL}/search-jobs"

REQUEST_TIMEOUT = 30
REQUEST_DELAY_SECONDS = 0.20
MAX_PAGES_PER_TERM = 25


def load_module(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module: {file_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Reuse existing canonical schema.
schema_module = load_module(
    "job_schema",
    SOURCE_DIR / "_job_search_v1A_001_schema_job_posting.py",
)
JobPosting = schema_module.JobPosting


# Reuse shared global search configuration.
config_module = load_module(
    "search_config",
    SOURCE_DIR / "_job_search_v1A_008_config_search_terms.py",
)
get_global_search_terms = config_module.get_global_search_terms


def create_session():
    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/154.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    session.verify = certifi.where()

    return session


def fetch_search_page(session, search_term, page_number):
    params = {
        "k": search_term,
        "p": page_number,
    }

    response = session.get(
        SEARCH_URL,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response.text, response.url


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def parse_job_link(anchor):
    """Map one Capital One search-result card to canonical JobPosting."""

    href = anchor.get("href", "").strip()

    if "/job/" not in href:
        return None

    full_url = urljoin(BASE_URL, href)

    job_id = clean_text(anchor.get("data-job-id", ""))

    if not job_id:
        job_id_match = re.search(r"/(\d+)(?:\?.*)?$", href)

        if not job_id_match:
            return None

        job_id = job_id_match.group(1)

    title_element = anchor.find("h2")
    date_element = anchor.find("span", class_="job-date-posted")
    location_element = anchor.find("span", class_="job-location")

    title = clean_text(
        title_element.get_text(" ", strip=True)
        if title_element else ""
    )

    posted_date = clean_text(
        date_element.get_text(" ", strip=True)
        if date_element else ""
    ) or None

    location = clean_text(
        location_element.get_text(" ", strip=True)
        if location_element else ""
    )

    if not title:
        return None

    return JobPosting(
        job_id=job_id,
        company_id="capital_one",
        company_name="Capital One",
        title=title,
        location=location,
        description="",
        apply_url=full_url,
        posted_date=posted_date,
        employment_type=None,
        clearance=None,
        source="capital_one_careers",
    )

def parse_jobs(html):
    soup = BeautifulSoup(html, "html.parser")

    anchors = [
        anchor
        for anchor in soup.find_all("a", href=True)
        if "/job/" in anchor.get("href", "")
    ]

    jobs = []

    for anchor in anchors:
        try:
            job = parse_job_link(anchor)

            if job is not None:
                job.validate()
                jobs.append(job)

        except Exception as exc:
            print(
                f"WARNING: skipped one malformed Capital One "
                f"job record: {exc}"
            )

    return jobs, soup


def has_next_page(soup, current_page):
    expected_next = current_page + 1

    for anchor in soup.find_all("a", href=True):
        text = clean_text(anchor.get_text(" ", strip=True)).lower()
        href = anchor.get("href", "")

        if text == "next":
            match = re.search(r"[?&]p=(\d+)", href)

            if match:
                return int(match.group(1)) == expected_next

            return True

    return False


def collect_jobs():
    search_terms = get_global_search_terms()
    session = create_session()

    jobs_by_id = {}

    total_requests = 0
    total_raw_records = 0

    print("=" * 78)
    print("CAPITAL ONE LIVE COLLECTOR")
    print("=" * 78)
    print(f"Global search terms : {len(search_terms)}")
    print(f"Max pages / term    : {MAX_PAGES_PER_TERM}")
    print()

    for term_number, search_term in enumerate(
        search_terms,
        start=1,
    ):
        print(
            f"[TERM {term_number:02d}/{len(search_terms):02d}] "
            f"{search_term}"
        )

        page_number = 1
        term_unique_ids = set()

        while page_number <= MAX_PAGES_PER_TERM:
            html, final_url = fetch_search_page(
                session,
                search_term,
                page_number,
            )

            total_requests += 1

            page_jobs, soup = parse_jobs(html)
            total_raw_records += len(page_jobs)

            new_on_page = 0

            for job in page_jobs:
                term_unique_ids.add(job.job_id)

                if job.job_id not in jobs_by_id:
                    jobs_by_id[job.job_id] = job
                    new_on_page += 1

            print(
                f"  Page {page_number:02d} | "
                f"records={len(page_jobs):02d} | "
                f"new_global={new_on_page:02d}"
            )

            if not page_jobs:
                break

            if not has_next_page(soup, page_number):
                break

            page_number += 1

            time.sleep(REQUEST_DELAY_SECONDS)

        print(
            f"  Unique jobs for term: {len(term_unique_ids)}"
        )
        print()

    jobs = list(jobs_by_id.values())

    jobs.sort(
        key=lambda job: (
            job.posted_date or "",
            job.job_id,
        ),
        reverse=True,
    )

    return jobs, total_requests, total_raw_records


def save_outputs(jobs):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "capital_one_jobs.json"
    csv_path = OUTPUT_DIR / "capital_one_jobs.csv"

    rows = [job.to_dict() for job in jobs]

    with open(
        json_path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            rows,
            f,
            ensure_ascii=False,
            indent=2,
        )

    fieldnames = [
        "job_id",
        "company_id",
        "company_name",
        "title",
        "location",
        "description",
        "apply_url",
        "posted_date",
        "employment_type",
        "clearance",
        "source",
    ]

    with open(
        csv_path,
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(rows)

    return json_path, csv_path


def main():
    jobs, total_requests, total_raw_records = collect_jobs()

    unique_ids = {job.job_id for job in jobs}

    duplicate_count = len(jobs) - len(unique_ids)

    print("=" * 78)
    print("CAPITAL ONE COLLECTION SUMMARY")
    print("=" * 78)

    print(f"HTTP requests       : {total_requests}")
    print(f"Raw matched records : {total_raw_records}")
    print(f"Unique jobs         : {len(jobs)}")
    print(f"Duplicate job IDs   : {duplicate_count}")

    if not jobs:
        raise RuntimeError(
            "Capital One collector returned zero jobs."
        )

    if duplicate_count != 0:
        raise RuntimeError(
            "Duplicate job IDs remain after deduplication."
        )

    json_path, csv_path = save_outputs(jobs)

    print(f"JSON output         : {json_path}")
    print(f"CSV output          : {csv_path}")

    print("\nSAMPLE JOBS")
    print("-" * 78)

    for job in jobs[:10]:
        print(
            f"{job.job_id} | "
            f"{job.posted_date or 'N/A'} | "
            f"{job.title} | "
            f"{job.location}"
        )

    print("\nCAPITAL ONE LIVE COLLECTOR : CLOSED PASS")


if __name__ == "__main__":
    main()
