import importlib
import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from uuid import uuid4

import boto3

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "source_codes"))


def lambda_handler(event, context):
    event = event or {}
    profile_id = event.get("profile_id")
    company_id = event.get("company_id")
    if (profile_id, company_id) != ("frank", "gdit"):
        raise ValueError("This V1B slice supports only frank/gdit")

    bucket = os.environ.get("JOB_SEARCH_RESULTS_BUCKET")
    if not bucket:
        raise RuntimeError("JOB_SEARCH_RESULTS_BUCKET is required")

    started = datetime.now(timezone.utc).isoformat()
    run_id = uuid4().hex
    module = importlib.import_module("_job_search_v1A_011_collector_gdit")
    jobs, raw_count, request_count = module.collect_jobs()
    rows = [job.to_dict() for job in jobs]

    targets = [j for j in rows if j["job_id"] == "RQ227420"]
    if len(targets) != 1:
        raise RuntimeError("Cloud acceptance check: RQ227420 must appear once")
    if targets[0]["clearance"] != "None; Public Trust: NACI (T1)":
        raise RuntimeError("Cloud acceptance check: Public Trust detail changed")

    prefix = f"runs/frank/{datetime.fromisoformat(started).astimezone(ZoneInfo('America/New_York')):%Y-%m-%d}/{run_id}"
    metadata = {
        "run_id": run_id,
        "profile_id": profile_id,
        "company_id": company_id,
        "started_at_utc": started,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "raw_hits": raw_count,
        "requests": request_count,
        "unique_jobs": len(rows),
        "target_job_id": "RQ227420",
        "status": "SUCCEEDED",
    }
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=bucket, Key=f"{prefix}/jobs.json",
        Body=json.dumps(rows, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )
    s3.put_object(
        Bucket=bucket, Key=f"{prefix}/metadata.json",
        Body=json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    print("JOB_SEARCH_RUN", json.dumps({
        **metadata, "s3_prefix": prefix
    }, ensure_ascii=False))
    return {"statusCode": 200, "body": {
        **metadata, "s3_bucket": bucket, "s3_prefix": prefix
    }}
