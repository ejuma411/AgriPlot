# listings/services/mock_ardhisasa.py

import random
import json
import time
from datetime import datetime, timedelta
from django.utils import timezone

class MockArdhisasaClient:
    """
    Mock client for Ardhisasa API testing
    Returns realistic test data without actual API calls
    """
    
    def __init__(self, use_mock=True):
        self.use_mock = use_mock
        self.base_url = "https://mock-ardhisasa.agriplot.com/api"
        
    def search_title(self, title_number, plot_details=None):
        """
        Mock title search response
        """
        # Simulate API delay
        import time
        time.sleep(1.5)  # Simulate network delay

        # If a mock registry record exists with this parcel number, return a deterministic success
        record = self._lookup_registry(title_number)
        if record:
            return self._generate_from_registry_record(record)

        # Strict registry match: if no registry plot, fail search
        return self._generate_not_found(title_number)
    
    def verify_ownership(self, title_number, owner_id_number, owner_name=None):
        """
        Mock ownership verification
        """
        time.sleep(1)

        # Deterministic mismatch for testing specific scenarios
        if "MISMATCH" in title_number.upper():
            return {
                'success': True,
                'verified': False,
                'title_number': title_number,
                'registered_owner': "JANE SMITH",
                'message': 'Owner name does not match registry records'
            }
        
        record = self._lookup_registry(title_number)
        if record:
            if owner_name and record.registered_owner_name.strip().lower() != (owner_name or "").strip().lower():
                return {
                    'success': True,
                    'verified': False,
                    'title_number': title_number,
                    'registered_owner': record.registered_owner_name,
                    'message': 'Owner name does not match registry records'
                }
            if owner_id_number and record.owner_id_number.strip().lower() != (owner_id_number or "").strip().lower():
                return {
                    'success': True,
                    'verified': False,
                    'title_number': title_number,
                    'registered_owner': record.registered_owner_name,
                    'message': 'Owner ID does not match registry records'
                }
            return {
                'success': True,
                'verified': True,
                'title_number': title_number,
                'registered_owner': record.registered_owner_name,
                'id_number': record.owner_id_number,
                'ownership_percentage': 100,
                'verification_date': timezone.now().isoformat(),
                'message': 'Ownership verified successfully'
            }

        # Default to success for mock runs if no registry exists
        return {
            'success': True,
            'verified': True,
            'title_number': title_number,
            'registered_owner': owner_name or "JOHN DOE",
            'id_number': owner_id_number,
            'ownership_percentage': 100,
            'verification_date': timezone.now().isoformat(),
            'message': 'Ownership verified successfully'
        }
    
    def get_encumbrances(self, title_number):
        """
        Mock encumbrance check
        """
        time.sleep(1)

        # Use mock registry record if present for deterministic encumbrance simulation
        record = self._lookup_registry(title_number)
        if record:
            has_issue = bool(record.is_charged or record.has_caution)
            if has_issue:
                return {
                    'success': True,
                    'title_number': title_number,
                    'encumbrances': [
                        {
                            'type': 'Charge',
                            'holder': 'Registry Simulation Bank',
                            'amount': '1,500,000',
                            'registration_date': (timezone.now() - timedelta(days=120)).isoformat(),
                            'status': 'Active',
                            'details': 'Encumbrance noted in registry record'
                        }
                    ],
                    'caveats': [
                        {
                            'lodged_by': 'Registry Simulation',
                            'reason': 'Caution on title' if record.has_caution else '',
                            'date': (timezone.now() - timedelta(days=45)).isoformat()
                        }
                    ] if record.has_caution else [],
                    'has_encumbrances': True
                }
            return {
                'success': True,
                'title_number': title_number,
                'encumbrances': [],
                'caveats': [],
                'has_encumbrances': False,
                'message': 'No encumbrances found'
            }

        # Default: no encumbrance unless registry provides it
        return {
            'success': True,
            'title_number': title_number,
            'encumbrances': [],
            'caveats': [],
            'has_encumbrances': False,
            'message': 'No encumbrances found'
        }
    
    def _generate_test_success(self, title_number, plot_details=None):
        """Generate successful response"""
        county = plot_details.get('county', 'Nairobi') if plot_details else 'Nairobi'
        
        parcel_from_request = None
        if plot_details:
            parcel_from_request = plot_details.get('parcel_number')

        return {
            'success': True,
            'status': 'verified',
            'title_number': title_number,
            'parcel_number': parcel_from_request or f"{county.upper()}/{random.randint(1000, 9999)}",
            'owner_name': 'JOHN MWANGI KAMAU',
            'owner_id': '12345678',
            'area_hectares': round(random.uniform(0.5, 10), 2),
            'registration_date': (timezone.now() - timedelta(days=random.randint(365, 3650))).isoformat(),
            'land_use': 'Agricultural',
            'lease_term': '99 years',
            'lease_expiry': (timezone.now() + timedelta(days=random.randint(365, 3650))).isoformat(),
            'verified': True,
            'verification_date': timezone.now().isoformat(),
            'search_reference': f"SR{random.randint(100000, 999999)}",
            'message': 'Title verified successfully'
        }

    def _generate_from_registry_record(self, record):
        """Generate deterministic response from a mock registry record."""
        area_hectares = float(record.acreage_ha) if record.acreage_ha else 0
        return {
            'success': True,
            'status': 'verified',
            'title_number': record.parcel_number,
            'parcel_number': record.parcel_number,
            'owner_name': record.registered_owner_name,
            'owner_id': record.owner_id_number,
            'area_hectares': area_hectares or 0,
            'registration_date': (timezone.now() - timedelta(days=800)).isoformat(),
            'land_use': 'Agricultural',
            'lease_term': 'Freehold' if record.land_type == 'FREEHOLD' else 'Leasehold',
            'lease_expiry': (timezone.now() + timedelta(days=1200)).isoformat(),
            'verified': True,
            'verification_date': timezone.now().isoformat(),
            'search_reference': f"SR{random.randint(100000, 999999)}",
            'has_encumbrances': bool(record.is_charged or record.has_caution),
            'message': 'Title verified successfully (registry match)'
        }

    def _lookup_registry(self, parcel_number):
        try:
            from registry_mock.models import MockLandRegistry
            return MockLandRegistry.objects.filter(parcel_number__iexact=parcel_number).first()
        except Exception:
            return None
    
    def _generate_with_encumbrances(self, title_number, plot_details=None):
        """Generate response with encumbrances"""
        base = self._generate_test_success(title_number, plot_details)
        base.update({
            'encumbrances': [
                {
                    'type': 'Charge',
                    'holder': 'Cooperative Bank',
                    'amount': '1,500,000',
                    'date': (timezone.now() - timedelta(days=90)).isoformat()
                }
            ],
            'caveats': [
                {
                    'lodged_by': 'MWANGI FAMILY TRUST',
                    'reason': 'Family dispute',
                    'date': (timezone.now() - timedelta(days=30)).isoformat()
                }
            ],
            'has_encumbrances': True,
            'message': 'Title has encumbrances'
        })
        return base
    
    def _generate_not_found(self, title_number, plot_details=None):
        """Generate not found response"""
        return {
            'success': False,
            'status': 'not_found',
            'title_number': title_number,
            'message': 'Title not found in registry',
            'error_code': 'TNF001',
            'suggestions': [
                'Verify title number format',
                'Check with county land registry',
                'Title may not be registered'
            ]
        }


# Pre-configured test cases for different scenarios
TEST_TITLES = {
    'VALID': {
        'title_number': 'TEST/2024/001',
        'expected': 'verified',
        'description': 'Valid title - should pass'
    },
    'INVALID': {
        'title_number': 'INVALID/2024/001',
        'expected': 'not_found',
        'description': 'Invalid title - should fail'
    },
    'ENCUMBRANCE': {
        'title_number': 'ENCUMBRANCE/2024/001',
        'expected': 'verified_with_encumbrances',
        'description': 'Valid title but has encumbrances'
    },
    'MISMATCH': {
        'title_number': 'TEST/2024/002',
        'expected': 'owner_mismatch',
        'description': 'Owner name mismatch'
    }
}
