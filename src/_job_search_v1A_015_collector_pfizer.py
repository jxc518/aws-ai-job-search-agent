"""Pfizer Workday collector: W. Y. pharmaceutical discovery profile."""
import csv
import json
import re
import sys
from pathlib import Path

import certifi
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source_codes"))
from _job_search_v1A_001_schema_job_posting import JobPosting
from _job_search_v1A_008_config_search_terms import get_profile_search_terms

ORIGIN = "https://pfizer.wd1.myworkdayjobs.com"
API = ORIGIN + "/wday/cxs/pfizer/PfizerCareers"
SITE = ORIGIN + "/en-US/PfizerCareers"
MAX_PAGES_PER_TERM = 3
PAGE_SIZE = 20
LEVEL = re.compile(r"\b(scientist|scientific|manager)\b", re.I)
EXCLUDE = re.compile(r"\b(intern(?:ship)?|fellow(?:ship)?|director)\b", re.I)
DOMAIN = re.compile(r"mass spectrometr|lc[- /]?ms|bioanalyt|biologic|"
                    r"protein|peptide|analytical|vaccine", re.I)


def request(session, method, path, **kwargs):
    r = session.request(method, API + path, timeout=30,
                        verify=certifi.where(), **kwargs)
    r.raise_for_status()
    return r.json()


def collect():
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    terms = get_profile_search_terms("family_a")
    candidates = {}
    errors = []
    requests_count = 0
    for term in terms:
        previous = set()
        for page in range(MAX_PAGES_PER_TERM):
            try:
                data = request(session, "POST", "/jobs", json={
                    "appliedFacets": {}, "limit": PAGE_SIZE,
                    "offset": PAGE_SIZE * page, "searchText": term})
                requests_count += 1
            except (requests.RequestException, ValueError) as exc:
                errors.append(f"search {term} page {page}: {exc}")
                break
            hits = data.get("jobPostings") or []
            print(f"TERM {term!r} page={page} hits={len(hits)} total={data.get('total')}")
            if not hits:
                break
            current = {(h.get("externalPath") or "") for h in hits}
            if current == previous:
                print("  STOP repeated page")
                break
            previous = current
            for hit in hits:
                path = hit.get("externalPath") or ""
                title = hit.get("title") or ""
                location = hit.get("locationsText") or ""
                if (path.startswith("/job/") and
                    location.startswith("United States") and
                    LEVEL.search(title) and not EXCLUDE.search(title) and
                    DOMAIN.search(title + " " + term)):
                    candidates[path] = hit
            if (page + 1) * PAGE_SIZE >= int(data.get("total") or 0):
                break
        else:
            print(f"  CAP {MAX_PAGES_PER_TERM} pages for {term!r}")
    rows = {}
    for path, hit in candidates.items():
        try:
            data = request(session, "GET", path)
            requests_count += 1
            info = data.get("jobPostingInfo") or {}
            title = info.get("title") or hit.get("title") or ""
            location = info.get("location") or hit.get("locationsText") or ""
            description = BeautifulSoup(info.get("jobDescription") or "",
                                        "html.parser").get_text(" ", strip=True)
            if (not location.startswith("United States") or
                not LEVEL.search(title) or EXCLUDE.search(title) or
                not DOMAIN.search(title + " " + description)):
                continue
            match = re.search(r"_(\d{5,})(?:-\d+)?$", path)
            job_id = match.group(1) if match else (info.get("jobReqId") or "")
            date = str(info.get("startDate") or "")[:10] or None
            job = JobPosting(job_id=str(job_id), company_id="pfizer",
                             company_name="Pfizer", title=title,
                             location=location, description=description,
                             apply_url=SITE + path, posted_date=date,
                             employment_type=None, clearance=None,
                             source="pfizer_workday_cxs")
            rows[job_id] = job.to_dict()
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"detail {path}: {exc}")
    output = ROOT / "outputs"
    output.mkdir(parents=True, exist_ok=True)
    jobs = sorted(rows.values(), key=lambda j: (j["posted_date"] or "",
                                                j["job_id"]), reverse=True)
    json_path = output / "pfizer_jobs.json"
    csv_path = output / "pfizer_jobs.csv"
    json_path.write_text(json.dumps(jobs, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(JobPosting.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(jobs)
    print(f"PFIZER | requests={requests_count} candidates={len(candidates)} US={len(jobs)} errors={len(errors)}")
    for error in errors[:10]:
        print("ERROR =", error[:250])
    print("OUTPUT", json_path, csv_path)
    if errors or not jobs:
        raise RuntimeError("Pfizer collection incomplete; inspect errors")
    return jobs


if __name__ == "__main__":
    collect()

