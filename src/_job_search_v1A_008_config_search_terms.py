import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOB_FAMILIES_FILE = PROJECT_ROOT / "config" / "job_families.json"


def load_job_families():
    """
    Load the canonical global job-family configuration.

    Expected structure:
    {
        "job_families": [
            {
                "family_id": "...",
                "keywords": [...]
            }
        ]
    }
    """
    with open(JOB_FAMILIES_FILE, "r", encoding="utf-8-sig") as f:
        payload = json.load(f)

    if not isinstance(payload, dict):
        raise ValueError("job_families.json top level must be a dictionary.")

    families = payload.get("job_families")

    if not isinstance(families, list):
        raise ValueError(
            "job_families.json['job_families'] must be a list."
        )

    for i, family in enumerate(families, start=1):
        if not isinstance(family, dict):
            raise ValueError(
                f"Job family #{i} must be a dictionary."
            )

        family_id = family.get("family_id")
        keywords = family.get("keywords")

        if not family_id:
            raise ValueError(
                f"Job family #{i} is missing family_id."
            )

        if not isinstance(keywords, list):
            raise ValueError(
                f"Job family '{family_id}' must contain a keywords list."
            )

    return families


def get_profile_search_terms(profile_id):
    """Return deduplicated search terms belonging only to one profile."""
    if profile_id not in {"frank", "family_a"}:
        raise ValueError(f"Unknown profile_id: {profile_id}")
    terms, seen = [], set()
    for family in load_job_families():
        if family.get("profile_id") != profile_id:
            continue
        for keyword in family["keywords"]:
            term = str(keyword).strip()
            if term and term.casefold() not in seen:
                seen.add(term.casefold())
                terms.append(term)
    if not terms:
        raise ValueError(f"No search terms configured for {profile_id}")
    return terms


def get_global_search_terms():
    """Legacy collector interface: Frank's search terms only."""
    return get_profile_search_terms("frank")


def get_search_terms_by_family():
    """
    Return:
        {
            "model_risk": [...],
            "data_science": [...],
            ...
        }

    This will later allow profile-specific family selection without
    changing individual company collectors.
    """
    families = load_job_families()

    return {
        family["family_id"]: list(family["keywords"])
        for family in families
    }


def main():
    families = load_job_families()
    terms = get_global_search_terms()
    by_family = get_search_terms_by_family()

    print("=" * 72)
    print("GLOBAL JOB SEARCH CONFIG")
    print("=" * 72)

    print(f"Config file   : {JOB_FAMILIES_FILE}")
    print(f"Job families  : {len(families)}")
    print(f"Search terms  : {len(terms)}")

    print("\nJOB FAMILIES")
    print("-" * 72)

    for family_id, keywords in by_family.items():
        print(
            f"{family_id:<20} : {len(keywords)} keywords"
        )

    print("\nGLOBAL SEARCH TERMS")
    print("-" * 72)

    for i, term in enumerate(terms, start=1):
        print(f"{i:02d}. {term}")

    if not terms:
        raise RuntimeError(
            "No global job search terms were loaded."
        )

    print("\nGLOBAL SEARCH CONFIG : CLOSED PASS")


if __name__ == "__main__":
    main()
