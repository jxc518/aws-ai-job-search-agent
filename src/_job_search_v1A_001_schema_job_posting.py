from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class JobPosting:
    """
    Canonical job-posting schema used by all company collectors.
    """

    job_id: str
    company_id: str
    company_name: str
    title: str
    location: str
    description: str
    apply_url: str

    posted_date: Optional[str] = None
    employment_type: Optional[str] = None
    clearance: Optional[str] = None
    source: Optional[str] = None

    def validate(self):
        required_fields = {
            "job_id": self.job_id,
            "company_id": self.company_id,
            "company_name": self.company_name,
            "title": self.title,
            "apply_url": self.apply_url,
        }

        missing = [
            field_name
            for field_name, value in required_fields.items()
            if not value or not str(value).strip()
        ]

        if missing:
            raise ValueError(
                f"Missing required job fields: {', '.join(missing)}"
            )

        return True

    def to_dict(self):
        self.validate()
        return asdict(self)
