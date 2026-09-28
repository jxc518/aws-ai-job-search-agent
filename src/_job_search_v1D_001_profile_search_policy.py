"""
V1D profile search policy.

Responsibilities:
- keep profile eligibility separate from company collectors
- normalize clearance into canonical categories
- enforce profile-specific clearance policy
- preserve raw JobPosting source truth

This module does NOT:
- call company backends
- modify JobPosting
- score jobs
- call SageMaker
- call Bedrock
"""

from dataclasses import dataclass
from typing import Optional


CLEARANCE_NONE = "NONE"
CLEARANCE_PUBLIC_TRUST = "PUBLIC_TRUST"
CLEARANCE_LOW_LEVEL = "LOW_LEVEL"
CLEARANCE_SECRET = "SECRET"
CLEARANCE_TOP_SECRET = "TOP_SECRET"
CLEARANCE_TS_SCI = "TS_SCI"
CLEARANCE_POLYGRAPH = "POLYGRAPH"
CLEARANCE_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProfileSearchPolicy:
    profile_id: str
    allowed_clearance_categories: frozenset[str]
    review_clearance_categories: frozenset[str]


PROFILE_POLICIES = {
    "frank": ProfileSearchPolicy(
        profile_id="frank",
        allowed_clearance_categories=frozenset({
            CLEARANCE_NONE,
            CLEARANCE_PUBLIC_TRUST,
            CLEARANCE_LOW_LEVEL,
        }),
        review_clearance_categories=frozenset({
            CLEARANCE_UNKNOWN,
        }),
    ),

    "family_a": ProfileSearchPolicy(
        profile_id="family_a",
        allowed_clearance_categories=frozenset({
            CLEARANCE_NONE,
            CLEARANCE_UNKNOWN,
        }),
        review_clearance_categories=frozenset(),
    ),
}


def normalize_clearance(raw_clearance: Optional[str]) -> str:
    """
    Convert company-specific clearance text into a canonical category.

    Important:
    This function classifies eligibility policy only.
    It never overwrites the raw JobPosting.clearance value.
    """

    if raw_clearance is None:
        return CLEARANCE_UNKNOWN

    text = str(raw_clearance).strip().casefold()

    if not text or text == "unknown":
        return CLEARANCE_UNKNOWN

    # Evaluate strongest/restrictive categories first.
    if "polygraph" in text or "poly " in text:
        return CLEARANCE_POLYGRAPH

    if (
        "ts/sci" in text
        or "ts sci" in text
        or "top secret/sci" in text
        or "top secret sci" in text
    ):
        return CLEARANCE_TS_SCI

    if "top secret" in text:
        return CLEARANCE_TOP_SECRET

    if "secret" in text:
        return CLEARANCE_SECRET

    if (
        "public trust" in text
        or "naci" in text
        or "tier 1" in text
        or "(t1)" in text
    ):
        return CLEARANCE_PUBLIC_TRUST

    none_markers = (
        "none",
        "no clearance",
        "not required",
        "no security clearance",
    )

    if any(marker in text for marker in none_markers):
        return CLEARANCE_NONE

    low_level_markers = (
        "suitability",
        "low risk",
        "moderate risk",
    )

    if any(marker in text for marker in low_level_markers):
        return CLEARANCE_LOW_LEVEL

    return CLEARANCE_UNKNOWN


def get_profile_policy(profile_id: str) -> ProfileSearchPolicy:
    try:
        return PROFILE_POLICIES[profile_id]
    except KeyError as exc:
        raise ValueError(f"Unknown profile_id: {profile_id}") from exc


def evaluate_clearance(profile_id: str, raw_clearance: Optional[str]) -> dict:
    policy = get_profile_policy(profile_id)
    category = normalize_clearance(raw_clearance)

    if category in policy.allowed_clearance_categories:
        decision = "ALLOW"
    elif category in policy.review_clearance_categories:
        decision = "REVIEW"
    else:
        decision = "REJECT"

    return {
        "profile_id": profile_id,
        "raw_clearance": raw_clearance,
        "clearance_category": category,
        "decision": decision,
    }


def main():
    tests = [
        ("frank", "None"),
        ("frank", "None; Public Trust: NACI (T1)"),
        ("frank", "Public Trust"),
        ("frank", "Suitability"),
        ("frank", "Secret"),
        ("frank", "Top Secret"),
        ("frank", "TS/SCI"),
        ("frank", "TS/SCI with Polygraph"),
        ("frank", None),
        ("family_a", "None"),
        ("family_a", "Secret"),
    ]

    print("=" * 72)
    print("V1D PROFILE SEARCH POLICY TEST")
    print("=" * 72)

    for profile_id, raw_clearance in tests:
        result = evaluate_clearance(profile_id, raw_clearance)

        print(
            f"{profile_id:<10} | "
            f"{str(raw_clearance):<32} | "
            f"{result['clearance_category']:<12} | "
            f"{result['decision']}"
        )

    # Critical V1C/V1D acceptance case.
    target = evaluate_clearance(
        "frank",
        "None; Public Trust: NACI (T1)",
    )

    if target["clearance_category"] != CLEARANCE_PUBLIC_TRUST:
        raise RuntimeError(
            "RQ227420-style Public Trust normalization failed"
        )

    if target["decision"] != "ALLOW":
        raise RuntimeError(
            "Frank Public Trust eligibility failed"
        )

    # Higher-clearance roles must remain excluded.
    for restricted in (
        "Secret",
        "Top Secret",
        "TS/SCI",
        "TS/SCI with Polygraph",
    ):
        result = evaluate_clearance("frank", restricted)

        if result["decision"] != "REJECT":
            raise RuntimeError(
                f"Restricted clearance incorrectly allowed: {restricted}"
            )

    print("\nV1D PROFILE SEARCH POLICY: CLOSED PASS")


if __name__ == "__main__":
    main()
