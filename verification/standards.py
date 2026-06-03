"""Canonical verification labels and document requirements."""

from collections import OrderedDict


IDENTITY_DOCUMENTS = OrderedDict(
    [
        ("national_id", "National ID / Passport"),
        ("kra_pin", "KRA PIN"),
    ]
)

LISTING_DOCUMENTS = OrderedDict(
    [
        ("title_deed", "Title Deed"),
        ("official_search", "Official Search Certificate"),
    ]
)

ROLE_REQUIREMENTS = {
    "buyer": [
        "National ID or passport",
        "KRA PIN",
    ],
    "landowner": [
        "National ID or passport",
        "KRA PIN",
        "Title deed for the land being listed",
        "Official search certificate for the parcel",
        "LCB consent when the parcel needs it",
    ],
    "agent": [
        "National ID",
        "License number and supporting license document",
        "KRA PIN certificate",
        "Tax compliance certificate where applicable",
        "Practicing certificate where applicable",
        "Certificate of good conduct where required",
        "Professional indemnity cover where required",
    ],
    "extension_officer": [
        "Official employee ID",
        "Designation and department",
        "Station or assigned office",
        "Qualifications and specializations",
        "Phone number and office address",
        "Assigned counties and task capacity",
    ],
    "land_surveyor": [
        "Professional license number",
        "Designation and station",
        "Qualifications and experience",
        "Phone number and office address",
        "Assigned counties and task capacity",
    ],
    "buyer_advocate": [
        "Advocate admission details",
        "Practising certificate",
        "National ID or passport",
        "KRA PIN",
    ],
    "seller_advocate": [
        "Advocate admission details",
        "Practising certificate",
        "National ID or passport",
        "KRA PIN",
    ],
    "lawyer": [
        "Professional admission details",
        "Practising certificate",
        "National ID or passport",
        "KRA PIN",
    ],
}


VERIFICATION_STAGE_GUIDE = OrderedDict(
    [
        (
            "document_uploaded",
            {
                "label": "Documents Uploaded",
                "summary": "The required files are in the system and waiting for review.",
            },
        ),
        (
            "api_verification_started",
            {
                "label": "API Verification Started",
                "summary": "Registry and compliance checks are running.",
            },
        ),
        (
            "title_search_completed",
            {
                "label": "Title Search Completed",
                "summary": "We have reviewed the title search response.",
            },
        ),
        (
            "owner_verified",
            {
                "label": "Owner Identity Verified",
                "summary": "Ownership details match the identity records on file.",
            },
        ),
        (
            "encumbrance_check",
            {
                "label": "Encumbrance Check",
                "summary": "We are checking for charges, restrictions, or disputes.",
            },
        ),
        (
            "physical_location_verified",
            {
                "label": "Physical Verification",
                "summary": "Field or map checks are confirming the parcel location.",
            },
        ),
        (
            "admin_review",
            {
                "label": "Under Admin Review",
                "summary": "An admin is doing the final review before approval.",
            },
        ),
        (
            "approved",
            {
                "label": "Approved",
                "summary": "The verification is complete and the listing can proceed.",
            },
        ),
        (
            "rejected",
            {
                "label": "Rejected",
                "summary": "The verification did not pass and needs correction.",
            },
        ),
    ]
)


def get_role_requirements(role):
    return ROLE_REQUIREMENTS.get(role, ROLE_REQUIREMENTS["buyer"])


def get_listing_document_types(role):
    """Return the document keys that should appear on the progress screen."""
    if role == "landowner":
        return list(IDENTITY_DOCUMENTS.keys()) + list(LISTING_DOCUMENTS.keys())
    return list(IDENTITY_DOCUMENTS.keys())


def get_document_label(document_type):
    return {
        **IDENTITY_DOCUMENTS,
        **LISTING_DOCUMENTS,
    }.get(document_type, document_type.replace("_", " ").title())


def get_stage_label(stage):
    return VERIFICATION_STAGE_GUIDE.get(stage, {}).get(
        "label", stage.replace("_", " ").title()
    )


def get_stage_summary(stage):
    return VERIFICATION_STAGE_GUIDE.get(stage, {}).get("summary", "")
