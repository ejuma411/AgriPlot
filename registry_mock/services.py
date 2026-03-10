from .models import MockLandRegistry


def _norm(value):
    return (value or "").strip().lower()


def verify_with_registry(parcel_no, owner_name=None, owner_id=None, owner_kra_pin=None):
    """
    Simulate a registry API lookup.
    Returns dict with verified flag, message, and record (if found).
    """
    parcel_no = (parcel_no or "").strip()
    if not parcel_no:
        return {"verified": False, "message": "Parcel number is required."}

    try:
        record = MockLandRegistry.objects.get(parcel_number__iexact=parcel_no)
    except MockLandRegistry.DoesNotExist:
        return {"verified": False, "message": "Parcel number not found in registry."}

    # Ownership checks (only enforce fields provided)
    if owner_name and _norm(record.registered_owner_name) != _norm(owner_name):
        return {"verified": False, "message": "Owner name does not match registry."}
    if owner_id and _norm(record.owner_id_number) != _norm(owner_id):
        return {"verified": False, "message": "Owner ID does not match registry."}
    if owner_kra_pin and record.owner_kra_pin and _norm(record.owner_kra_pin) != _norm(owner_kra_pin):
        return {"verified": False, "message": "KRA PIN does not match registry."}

    return {
        "verified": True,
        "message": "Ownership match found.",
        "record": record,
        "has_encumbrances": bool(record.is_charged or record.has_caution),
    }
