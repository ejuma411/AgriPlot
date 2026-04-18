import re
import socket

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator


KENYAN_PHONE_PATTERN = re.compile(
    r'^(\+?254|0)?\s*([7|1][0-9]{2})\s*([0-9]{3})\s*([0-9]{3})$'
)
PERSON_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z\s'.-]{1,49}$")
ID_NUMBER_PATTERN = re.compile(r"^\d{6,12}$")
LICENSE_NUMBER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/\-]{3,99}$")
def normalize_email(value):
    return (value or "").strip().lower()


def validate_kenyan_phone(value):
    """
    Validate Kenyan phone numbers with exact digit counts based on format.
    
    Format rules:
    - Starts with 0: expects 10 digits total (e.g., 0712345678)
    - Starts with +254: expects 12 digits after + (e.g., +254712345678)
    - Starts with 254: expects 12 digits total (e.g., 254712345678)
    - Starts with 7 or 1: expects 9 digits total (e.g., 712345678)
    """
    raw_value = str(value or "").strip()
    
    if not raw_value:
        raise ValidationError("Phone number is required.")
    
    # Remove spaces, dashes, parentheses
    cleaned = re.sub(r'[\s\-\(\)]', '', raw_value)
    
    # Check format and exact digit count
    if cleaned.startswith('0'):
        # Format: 07XXXXXXXX or 01XXXXXXXX (10 digits total)
        if len(cleaned) != 10:
            raise ValidationError(
                "Phone number starting with 0 must have exactly 10 digits. "
                f"Current length: {len(cleaned)} digits (expected: 10)"
            )
        if not re.match(r'^(07|01)\d{8}$', cleaned):
            raise ValidationError(
                "Phone number starting with 0 must begin with 07 or 01 followed by 8 digits."
            )
        normalized = f"+254{cleaned[1:]}"
        
    elif cleaned.startswith('+254'):
        # Format: +254XXXXXXXXX (12 digits after +)
        digits_after_plus = cleaned[1:]
        if len(digits_after_plus) != 12:
            raise ValidationError(
                "Phone number starting with +254 must have exactly 12 digits after the +. "
                f"Current length: {len(digits_after_plus)} digits (expected: 12)"
            )
        if not re.match(r'^254[7|1]\d{8}$', digits_after_plus):
            raise ValidationError(
                "After +254, the number must start with 7 or 1 followed by 8 digits."
            )
        normalized = cleaned
        
    elif cleaned.startswith('254'):
        # Format: 254XXXXXXXXX (12 digits total)
        if len(cleaned) != 12:
            raise ValidationError(
                "Phone number starting with 254 must have exactly 12 digits total. "
                f"Current length: {len(cleaned)} digits (expected: 12)"
            )
        if not re.match(r'^254[7|1]\d{8}$', cleaned):
            raise ValidationError(
                "After 254, the number must start with 7 or 1 followed by 8 digits."
            )
        normalized = f"+{cleaned}"
        
    elif cleaned.startswith('7') or cleaned.startswith('1'):
        # Format: 7XXXXXXXX or 1XXXXXXXX (9 digits total)
        if len(cleaned) != 9:
            raise ValidationError(
                "Phone number starting with 7 or 1 must have exactly 9 digits. "
                f"Current length: {len(cleaned)} digits (expected: 9)"
            )
        if not re.match(r'^[7|1]\d{8}$', cleaned):
            raise ValidationError(
                "Phone number must start with 7 or 1 followed by 8 digits."
            )
        normalized = f"+254{cleaned}"
        
    else:
        raise ValidationError(
            "Invalid phone number format. "
            "Use one of: 0712345678 (10 digits), +254712345678 (12 digits after +), "
            "254712345678 (12 digits), or 712345678 (9 digits)"
        )
    
    return normalized


def validate_person_name(value, field_label="This field"):
    normalized = " ".join(str(value or "").strip().split())
    if not normalized:
        raise ValidationError(f"{field_label} is required.")
    if not PERSON_NAME_PATTERN.match(normalized):
        raise ValidationError(
            f"{field_label} should contain letters only, plus spaces, apostrophes, dots, or hyphens."
        )
    return normalized


def validate_national_id_number(value):
    normalized = str(value or "").strip()
    if not ID_NUMBER_PATTERN.match(normalized):
        raise ValidationError("Enter a valid national ID number using 6 to 12 digits only.")
    return normalized


def validate_license_number(value):
    normalized = str(value or "").strip().upper()
    if not LICENSE_NUMBER_PATTERN.match(normalized):
        raise ValidationError(
            "Enter a valid license number using letters, numbers, slashes, or hyphens only."
        )
    return normalized


def email_validation_report(value):
    email = normalize_email(value)
    if not email:
        return {
            "normalized": "",
            "valid": False,
            "domain_exists": False,
            "message": "Enter an email address.",
        }

    validator = EmailValidator(message="Enter a valid email address.")
    try:
        validator(email)
    except ValidationError as exc:
        return {
            "normalized": email,
            "valid": False,
            "domain_exists": False,
            "message": exc.messages[0],
        }

    domain = email.rsplit("@", 1)[-1]
    try:
        ascii_domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        return {
            "normalized": email,
            "valid": False,
            "domain_exists": False,
            "message": "Enter a valid email domain.",
        }

    try:
        socket.getaddrinfo(ascii_domain, None)
    except socket.gaierror:
        return {
            "normalized": email,
            "valid": False,
            "domain_exists": False,
            "message": "This email domain does not appear to accept mail.",
        }

    return {
        "normalized": email,
        "valid": True,
        "domain_exists": True,
        "message": "Email format and domain look valid.",
    }


def validate_realistic_email(value):
    report = email_validation_report(value)
    if not report["valid"]:
        raise ValidationError(report["message"])
    return report["normalized"]
