# services/ardhisasa_service.py
import requests
import logging
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)

class ArdhisasaVerificationService:
    """
    Service to handle Ardhisasa API integration for land verification
    """
    
    def __init__(self, verification_obj):
        self.verification = verification_obj
        self.base_url = settings.ARDHISASA_API_URL
        self.api_key = settings.ARDHISASA_API_KEY
    
    def start_verification(self):
        """Start the verification process"""
        
        # Update status
        self.verification.update_stage('api_verification_started')
        
        # Step 1: Title search
        title_result = self.search_title()
        if not title_result['success']:
            return self.handle_failure(title_result)
        
        # Step 2: Verify owner identity
        owner_result = self.verify_owner()
        if not owner_result['success']:
            return self.handle_failure(owner_result)
        
        # Step 3: Check encumbrances
        encumbrance_result = self.check_encumbrances()
        
        # Step 4: If all successful, move to admin review
        self.verification.update_stage('admin_review', {
            'title_search': title_result,
            'owner_verification': owner_result,
            'encumbrance_check': encumbrance_result
        })
        
        return {
            'success': True,
            'message': 'API verification complete. Awaiting admin review.',
            'stages': {
                'title_search': title_result,
                'owner_verification': owner_result,
                'encumbrance_check': encumbrance_result
            }
        }
    
    def search_title(self):
        """Step 1: Search title on Ardhisasa"""
        try:
            # Simulated API call - replace with actual Ardhisasa API
            response = self.mock_title_search()
            
            self.verification.add_api_response({
                'stage': 'title_search',
                'response': response
            })
            
            if response['verified']:
                self.verification.update_stage('title_search_completed', {
                    'search_reference': response['reference'],
                    'owner': response['registered_owner'],
                    'parcel': response['parcel_details']
                })
                self.verification.search_reference = response['reference']
                self.verification.search_fee_paid = response['fee']
                self.verification.save()
                
                return {'success': True, 'data': response}
            else:
                return {'success': False, 'error': response['message']}
                
        except Exception as e:
            logger.error(f"Title search failed: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def verify_owner(self):
        """Step 2: Verify owner identity matches"""
        # Implementation
        pass
    
    def check_encumbrances(self):
        """Step 3: Check for any caveats or charges"""
        # Implementation
        pass
    
    def mock_title_search(self):
        """Mock Ardhisasa response for FYP"""
        return {
            'verified': True,
            'reference': f"SRCH{timezone.now().strftime('%Y%m%d%H%M%S')}",
            'registered_owner': self.get_owner_name(),
            'parcel_details': {
                'title_number': self.get_title_number(),
                'size': '5.0 acres',
                'registration_date': '2020-01-15',
                'land_use': 'Agricultural'
            },
            'encumbrances': [],
            'fee': 500,
            'message': 'Title verified successfully'
        }
    
    def get_owner_name(self):
        """Extract owner name from verification object"""
        if hasattr(self.verification.content_object, 'user'):
            return self.verification.content_object.user.get_full_name()
        return "Unknown"
    
    def get_title_number(self):
        """Extract title number from documents"""
        # In real implementation, you'd parse from uploaded documents
        return f"TITLE/{timezone.now().year}/{self.verification.id}"
    
    def handle_failure(self, result):
        """Handle verification failure"""
        self.verification.update_stage('rejected', {
            'reason': result.get('error', 'Verification failed'),
            'details': result
        })
        return {'success': False, 'error': result.get('error')}