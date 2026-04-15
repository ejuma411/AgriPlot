import re
import socket

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator


KENYAN_PHONE_PATTERN = re.compile(r"^(?:\+?254|0)?7\d{8}$")
PERSON_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z\s'.-]{1,49}$")
ID_NUMBER_PATTERN = re.compile(r"^\d{6,12}$")
LICENSE_NUMBER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/\-]{3,99}$")
def normalize_email(value):
    return (value or "").strip().lower()


def normalize_kenyan_phone(value):
    phone = str(value or "").strip().replace(" ", "")
    if phone.startswith("+"):
        phone = phone[1:]
    if phone.startswith("0"):
        phone = "254" + phone[1:]
    elif phone.startswith("7"):
        phone = "254" + phone
    return phone


def validate_kenyan_phone(value):
    raw_value = str(value or "").strip()
    if not raw_value:
        raise ValidationError("Enter a Kenyan phone number.")
    if not KENYAN_PHONE_PATTERN.match(raw_value):
        raise ValidationError(
            "Enter a valid Kenyan phone number (e.g., 0712345678 or +254712345678)."
        )
    return normalize_kenyan_phone(raw_value)


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
