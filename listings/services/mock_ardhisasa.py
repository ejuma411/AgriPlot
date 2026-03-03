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
        
        # Generate realistic mock data based on title number
        if "TEST" in title_number.upper():
            return self._generate_test_success(title_number, plot_details)
        elif "INVALID" in title_number.upper():
            return self._generate_not_found(title_number)
        elif "ENCUMBRANCE" in title_number.upper():
            return self._generate_with_encumbrances(title_number)
        else:
            # Randomly choose response for realistic testing
            return random.choice([
                self._generate_test_success,
                self._generate_with_encumbrances,
                self._generate_not_found
            ])(title_number, plot_details)
    
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
        
        # Randomly decide if there are encumbrances
        has_encumbrances = random.random() < 0.3
        
        if has_encumbrances:
            return {
                'success': True,
                'title_number': title_number,
                'encumbrances': [
                    {
                        'type': 'Mortgage',
                        'holder': 'Kenya Commercial Bank',
                        'amount': '2,500,000',
                        'registration_date': (timezone.now() - timedelta(days=180)).isoformat(),
                        'status': 'Active'
                    }
                ],
                'caveats': [],
                'has_encumbrances': True
            }
        else:
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
        
        return {
            'success': True,
            'status': 'verified',
            'title_number': title_number,
            'parcel_number': f"{county.upper()}/{random.randint(1000, 9999)}",
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
