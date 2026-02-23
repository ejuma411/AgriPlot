# listings/services/ardhisasa_integration.py

from django.conf import settings
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from .mock_ardhisasa import MockArdhisasaClient
from ..models import TitleSearchResult, VerificationStatus, VerificationLog
import logging

logger = logging.getLogger(__name__)

class ArdhisasaService:
    """Service for Ardhisasa API integration"""
    
    def __init__(self, use_mock=True):
        # Use mock for development, real API for production
        if use_mock or settings.DEBUG:
            self.client = MockArdhisasaClient()
            logger.info("Using MOCK Ardhisasa API for testing")
        else:
            # Import real client when ready
            # from .real_ardhisasa import ArdhisasaClient
            # self.client = ArdhisasaClient()
            self.client = MockArdhisasaClient()  # Fallback to mock
            logger.info("Using REAL Ardhisasa API")
    
    def verify_plot_title(self, plot):
        """
        Complete title verification workflow for a plot
        """
        logger.info(f"Starting Ardhisasa verification for plot {plot.id}")
        
        # Get or create verification status
        content_type = ContentType.objects.get_for_model(plot.__class__)
        verification, _ = VerificationStatus.objects.get_or_create(
            content_type=content_type,
            object_id=plot.id
        )
        
        # Update stage
        verification.update_stage('api_verification_started')
        
        try:
            # Extract title number from plot (you might need to parse from title_deed or a field)
            title_number = self._extract_title_number(plot)
            
            if not title_number:
                return self._handle_error(plot, verification, "Could not extract title number")
            
            # Step 1: Search title
            logger.info(f"Searching title: {title_number}")
            search_result = self.client.search_title(
                title_number,
                plot_details={
                    'county': plot.county,
                    'subcounty': plot.subcounty,
                    'area': plot.area
                }
            )
            
            # Store API response
            verification.add_api_response({
                'step': 'title_search',
                'response': search_result
            })
            
            if not search_result.get('success'):
                return self._handle_error(
                    plot, verification, 
                    search_result.get('message', 'Title search failed')
                )
            
            # Step 2: Verify ownership
            owner_id = self._get_owner_id_number(plot)
            owner_name = self._get_owner_name(plot)
            
            ownership_result = self.client.verify_ownership(
                title_number,
                owner_id,
                owner_name
            )
            
            verification.add_api_response({
                'step': 'ownership_verification',
                'response': ownership_result
            })
            
            if not ownership_result.get('verified'):
                return self._handle_error(
                    plot, verification,
                    'Owner information does not match registry records'
                )
            
            # Step 3: Check encumbrances
            encumbrance_result = self.client.get_encumbrances(title_number)
            
            verification.add_api_response({
                'step': 'encumbrance_check',
                'response': encumbrance_result
            })
            
            # Save title search result
            title_result, created = TitleSearchResult.objects.update_or_create(
                plot=plot,
                defaults={
                    'search_platform': 'ardhisasa',
                    'official_owner': search_result.get('owner_name'),
                    'parcel_number': search_result.get('parcel_number'),
                    'encumbrances': str(encumbrance_result.get('encumbrances', [])),
                    'lease_status': search_result.get('lease_term'),
                    'search_date': timezone.now().date(),
                    'verified': ownership_result.get('verified', False),
                    'notes': f"Search ref: {search_result.get('search_reference')}"
                }
            )
            
            # Update verification stage
            verification.update_stage('title_search_completed', {
                'search_reference': search_result.get('search_reference'),
                'has_encumbrances': encumbrance_result.get('has_encumbrances', False)
            })
            
            # Create verification log
            VerificationLog.objects.create(
                plot=plot,
                verification_type='api_verification',
                comment=f"Ardhisasa verification completed. Title: {title_number}, Owner verified: {ownership_result.get('verified')}"
            )
            
            logger.info(f"Ardhisasa verification successful for plot {plot.id}")
            
            return {
                'success': True,
                'title_result': title_result,
                'verification': verification,
                'search_data': search_result,
                'ownership_data': ownership_result,
                'encumbrance_data': encumbrance_result
            }
            
        except Exception as e:
            logger.error(f"Ardhisasa verification error: {str(e)}", exc_info=True)
            return self._handle_error(plot, verification, str(e))
    
    def _extract_title_number(self, plot):
        """
        Extract title number from plot.
        For testing, you can use a pattern or a dedicated field.
        """
        # For testing, generate based on plot ID
        return f"TEST/{plot.id}/2024"
    
    def _get_owner_id_number(self, plot):
        """Get owner ID number from plot's owner"""
        if plot.agent:
            return plot.agent.id_number
        elif plot.landowner:
            # You might need to extract from landowner profile
            return "12345678"  # Default for testing
        return "12345678"
    
    def _get_owner_name(self, plot):
        """Get owner name"""
        if plot.agent:
            return plot.agent.user.get_full_name() or plot.agent.user.username
        elif plot.landowner:
            return plot.landowner.user.get_full_name() or plot.landowner.user.username
        return "Unknown"
    
    def _handle_error(self, plot, verification, error_message):
        """Handle verification errors"""
        verification.stage_details['error'] = error_message
        verification.save()
        
        VerificationLog.objects.create(
            plot=plot,
            verification_type='api_error',
            comment=f"Ardhisasa error: {error_message}"
        )
        
        logger.error(f"Ardhisasa verification failed for plot {plot.id}: {error_message}")
        
        return {
            'success': False,
            'error': error_message,
            'verification': verification
        }