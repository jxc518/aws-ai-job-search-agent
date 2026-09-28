"""
V1D canonical result composer.

Consumes the existing flat V1C evidence contract and V1D profile-policy truth.

Does NOT:
- recompute SageMaker scores
- reinterpret SageMaker scores as probabilities
- rerun Bedrock
- override Bedrock review status
- overwrite raw clearance
"""

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"

V1C_EVIDENCE_FILE = (
    OUTPUT_DIR / "v1c_frank_RQ227420_evidence.json"
)

V1D_OUTPUT_FILE = (
    OUTPUT_DIR / "v1d_frank_RQ227420_result.json"
)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(
        name,
        path,
    )

    if spec is None or spec.loader is None:
        raise ImportError(
            f"Cannot load module: {path}"
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


POLICY_MODULE = load_module(
    "v1d_profile_policy",
    SOURCE_DIR
    / "_job_search_v1D_001_profile_search_policy.py",
)


def load_json(path):
    with open(
        path,
        "r",
        encoding="utf-8-sig",
    ) as f:
        payload = json.load(f)

    if not isinstance(payload, dict):
        raise ValueError(
            f"Expected JSON object: {path}"
        )

    return payload


def validate_v1c_contract(evidence):
    """
    Validate the ACTUAL proven flat V1C evidence contract.
    """

    required = {
        "profile_id",
        "company_id",
        "job_id",
        "title",
        "apply_url",
        "clearance",
        "created_at_utc",
        "sagemaker",
        "bedrock",
    }

    missing = sorted(
        required - set(evidence)
    )

    if missing:
        raise ValueError(
            "V1C evidence missing fields: "
            + ", ".join(missing)
        )

    if not isinstance(
        evidence["sagemaker"],
        dict,
    ):
        raise ValueError(
            "V1C sagemaker must be a dictionary"
        )

    if not isinstance(
        evidence["bedrock"],
        dict,
    ):
        raise ValueError(
            "V1C bedrock must be a dictionary"
        )

    return True


def compose_result(evidence):
    validate_v1c_contract(evidence)

    clearance_evaluation = (
        POLICY_MODULE.evaluate_clearance(
            evidence["profile_id"],
            evidence["clearance"],
        )
    )

    sagemaker = evidence["sagemaker"]
    bedrock = evidence["bedrock"]

    result = {
        "schema_version": "v1d.1",

        "composed_at_utc": (
            datetime.now(timezone.utc).isoformat()
        ),

        "identity": {
            "profile_id": evidence["profile_id"],
            "company_id": evidence["company_id"],
            "job_id": evidence["job_id"],
        },

        "job": {
            "job_id": evidence["job_id"],
            "company_id": evidence["company_id"],
            "title": evidence["title"],
            "apply_url": evidence["apply_url"],
            "clearance": evidence["clearance"],
        },

        "eligibility": {
            "clearance": clearance_evaluation,
        },

        "ranking": {
            "provider": "sagemaker",

            "model_output_score": (
                sagemaker.get(
                    "model_output_score"
                )
            ),

            "score_limit": (
                sagemaker.get(
                    "score_limit"
                )
            ),

            "source_training_job": (
                sagemaker.get(
                    "training_job"
                )
            ),

            "source_transform_job": (
                sagemaker.get(
                    "transform_job"
                )
            ),
        },

        "review": {
            "provider": "bedrock",

            "model_id": (
                bedrock.get("model_id")
            ),

            "explanation": (
                bedrock.get("explanation")
            ),

            "evidence_limit": (
                bedrock.get(
                    "evidence_limit"
                )
            ),

            "human_review_status": (
                bedrock.get(
                    "human_review_status"
                )
            ),

            "usage": (
                bedrock.get("usage")
            ),
        },

        "provenance": {
            "v1c_evidence_file": (
                V1C_EVIDENCE_FILE.name
            ),

            "v1c_created_at_utc": (
                evidence["created_at_utc"]
            ),

            "sagemaker_truth_preserved": True,
            "bedrock_truth_preserved": True,
            "raw_clearance_preserved": True,
        },
    }

    return result


def validate_result(result):
    identity = result["identity"]
    job = result["job"]

    clearance = (
        result["eligibility"]["clearance"]
    )

    ranking = result["ranking"]
    review = result["review"]
    provenance = result["provenance"]

    if identity != {
        "profile_id": "frank",
        "company_id": "gdit",
        "job_id": "RQ227420",
    }:
        raise RuntimeError(
            "Acceptance failure: identity changed"
        )

    if job["title"] != (
        "Data Scientist Principal"
    ):
        raise RuntimeError(
            "Acceptance failure: title changed"
        )

    if job["clearance"] != (
        "None; Public Trust: NACI (T1)"
    ):
        raise RuntimeError(
            "Acceptance failure: "
            "raw clearance changed"
        )

    if clearance["raw_clearance"] != (
        job["clearance"]
    ):
        raise RuntimeError(
            "Acceptance failure: "
            "policy raw clearance differs "
            "from source truth"
        )

    if clearance[
        "clearance_category"
    ] != "PUBLIC_TRUST":
        raise RuntimeError(
            "Acceptance failure: "
            "clearance normalization"
        )

    if clearance["decision"] != "ALLOW":
        raise RuntimeError(
            "Acceptance failure: "
            "Frank clearance eligibility"
        )

    if ranking[
        "model_output_score"
    ] != 0.8922722935676575:
        raise RuntimeError(
            "Acceptance failure: "
            "SageMaker score changed"
        )

    expected_limit = (
        "Small-sample demonstration; "
        "not a calibrated probability"
    )

    if ranking["score_limit"] != expected_limit:
        raise RuntimeError(
            "Acceptance failure: "
            "SageMaker limitation changed"
        )

    if review["model_id"] != (
        "us.amazon.nova-2-lite-v1:0"
    ):
        raise RuntimeError(
            "Acceptance failure: "
            "Bedrock model changed"
        )

    if review[
        "human_review_status"
    ] != (
        "NOT APPROVED FOR WEBSITE DISPLAY"
    ):
        raise RuntimeError(
            "Acceptance failure: "
            "Bedrock review status changed"
        )

    expected_evidence_limit = (
        "Only verified project facts were "
        "supplied. Full resume and professional "
        "history were not evaluated."
    )

    if review[
        "evidence_limit"
    ] != expected_evidence_limit:
        raise RuntimeError(
            "Acceptance failure: "
            "Bedrock evidence limitation changed"
        )

    if not provenance[
        "sagemaker_truth_preserved"
    ]:
        raise RuntimeError(
            "SageMaker provenance failure"
        )

    if not provenance[
        "bedrock_truth_preserved"
    ]:
        raise RuntimeError(
            "Bedrock provenance failure"
        )

    if not provenance[
        "raw_clearance_preserved"
    ]:
        raise RuntimeError(
            "Clearance provenance failure"
        )

    return True


def main():
    print("=" * 72)
    print(
        "V1D CANONICAL RESULT COMPOSITION"
    )
    print("=" * 72)

    evidence = load_json(
        V1C_EVIDENCE_FILE
    )

    validate_v1c_contract(evidence)

    print(
        "V1C CONTRACT       = PASS"
    )

    result = compose_result(evidence)

    validate_result(result)

    print(
        "V1D CONTRACT       = PASS"
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(
        V1D_OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            result,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(
        "PROFILE + JOB      =",
        result["identity"]["profile_id"],
        result["identity"]["job_id"],
    )

    print(
        "CLEARANCE RAW      =",
        result["job"]["clearance"],
    )

    print(
        "CLEARANCE CATEGORY =",
        result["eligibility"][
            "clearance"
        ]["clearance_category"],
    )

    print(
        "ELIGIBILITY        =",
        result["eligibility"][
            "clearance"
        ]["decision"],
    )

    print(
        "SAGEMAKER SCORE    =",
        result["ranking"][
            "model_output_score"
        ],
    )

    print(
        "SCORE LIMIT        =",
        result["ranking"][
            "score_limit"
        ],
    )

    print(
        "BEDROCK MODEL      =",
        result["review"]["model_id"],
    )

    print(
        "BEDROCK REVIEW     =",
        result["review"][
            "human_review_status"
        ],
    )

    print(
        "OUTPUT             =",
        V1D_OUTPUT_FILE,
    )

    print(
        "\nV1D CANONICAL RESULT "
        "COMPOSITION: CLOSED PASS"
    )


if __name__ == "__main__":
    main()
