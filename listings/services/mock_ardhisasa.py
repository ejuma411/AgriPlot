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

        # If a registry plot exists with this parcel number, return a deterministic success
        try:
            from listings.models import Plot
            registry_plot = Plot.objects.filter(
                parcel_number__iexact=title_number,
                is_registry_record=True
            ).first()
        except Exception:
            registry_plot = None

        if registry_plot:
            return self._generate_from_registry(registry_plot)

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
        
        # Default to success for mock runs
        if random.random() < 0.98:
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
        else:
            return {
                'success': True,
                'verified': False,
                'title_number': title_number,
                'registered_owner': "JANE SMITH",
                'message': 'Owner name does not match registry records'
            }
    
    def get_encumbrances(self, title_number):
        """
        Mock encumbrance check
        """
        time.sleep(1)

        # Use registry record if present for deterministic encumbrance simulation
        try:
            from listings.models import Plot
            registry_plot = Plot.objects.filter(
                parcel_number__iexact=title_number,
                is_registry_record=True
            ).first()
        except Exception:
            registry_plot = None

        if registry_plot:
            if registry_plot.encumbrances:
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
                            'details': registry_plot.encumbrance_details or 'Encumbrance noted in registry record'
                        }
                    ],
                    'caveats': [],
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

    def _generate_from_registry(self, plot):
        """Generate deterministic response from a registry plot record."""
        area_hectares = None
        if plot.area_acres:
            area_hectares = round(plot.area_acres / 2.47105, 2)
        owner_name = plot.owner_full_name or None
        if not owner_name:
            if plot.agent:
                owner_name = plot.agent.user.get_full_name() or plot.agent.user.username
            elif plot.landowner:
                owner_name = plot.landowner.user.get_full_name() or plot.landowner.user.username

        return {
            'success': True,
            'status': 'verified',
            'title_number': plot.parcel_number,
            'parcel_number': plot.parcel_number,
            'owner_name': owner_name or "UNKNOWN",
            'owner_id': getattr(plot.agent, 'id_number', None) or "12345678",
            'area_hectares': area_hectares or 0,
            'registration_date': (timezone.now() - timedelta(days=800)).isoformat(),
            'land_use': plot.get_land_type_display() if plot.land_type else 'Agricultural',
            'lease_term': '99 years',
            'lease_expiry': (timezone.now() + timedelta(days=1200)).isoformat(),
            'verified': True,
            'verification_date': timezone.now().isoformat(),
            'search_reference': f"SR{random.randint(100000, 999999)}",
            'has_encumbrances': bool(plot.encumbrances),
            'message': 'Title verified successfully (registry match)'
        }
    
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
