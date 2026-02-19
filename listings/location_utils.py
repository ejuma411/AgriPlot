from .kenya_data import KENYA_COUNTIES, KENYA_SUB_COUNTIES

def validate_kenyan_location(county, subcounty):
    """
    Validate that a county and subcounty combination is valid in Kenya.
    Returns (is_valid, error_message)
    """
    if not county:
        return False, "County is required"
    
    if county not in KENYA_COUNTIES:
        return False, f"'{county}' is not a valid Kenyan county"
    
    if not subcounty:
        return False, "Sub-county is required"
    
    valid_subcounties = KENYA_SUB_COUNTIES.get(county, [])
    if subcounty not in valid_subcounties:
        return False, f"'{subcounty}' is not a valid sub-county for {county}"
    
    return True, "Location is valid"

def get_subcounties_for_county(county):
    """Return list of subcounties for a given county"""
    return KENYA_SUB_COUNTIES.get(county, [])

def get_all_counties():
    """Return list of all Kenyan counties"""
    return KENYA_COUNTIES.copy()