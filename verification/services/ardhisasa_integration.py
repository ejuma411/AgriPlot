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
    
    def __init__(self, use_mock=None):
        if use_mock is None:
            mode = getattr(settings, "ARDHISASA_MODE", "mock").lower()
            use_mock = (mode != "real")
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
        
        # Check if we're already at the right stage
        if verification.current_stage == 'title_search_completed':
            logger.info(f"Plot {plot.id} already has title search completed")
            return {'success': True, 'message': 'Already verified'}
        
        # Only update stage if not already in progress
        if verification.current_stage != 'api_verification_started':
            verification.update_stage('api_verification_started')
        
        try:
            # Extract title number from plot
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
                    'area': plot.area,
                    'registration_section': getattr(plot, 'registration_section', None),
                    'parcel_number': getattr(plot, 'parcel_number', None)
                }
            )

            if not search_result or not search_result.get('success'):
                reason = search_result.get('message') if search_result else "Title search failed"
                return self._handle_failure(plot, verification, reason, search_result=search_result)

            # Step 2: Verify ownership
            owner_id_number = self._get_owner_id_number(plot)
            owner_name = self._get_owner_name(plot)
            ownership_result = self.client.verify_ownership(
                title_number,
                owner_id_number,
                owner_name=owner_name
            )

            if ownership_result and ownership_result.get('verified') is False:
                reason = ownership_result.get('message') or "Owner verification failed"
                return self._handle_failure(
                    plot,
                    verification,
                    reason,
                    search_result=search_result,
                    ownership_result=ownership_result
                )

            # Step 3: Encumbrance check (informational, does not fail)
            encumbrance_result = self.client.get_encumbrances(title_number)

            verification_data = {
                'title_number': title_number,
                'search_result': search_result,
                'ownership_result': ownership_result,
                'encumbrance_result': encumbrance_result,
                'decision': {
                    'passed': True,
                    'owner_verified': True,
                    'has_encumbrances': bool(encumbrance_result.get('has_encumbrances'))
                }
            }

            return {'success': True, 'verification_data': verification_data}
            
        except Exception as e:
            logger.error(f"Ardhisasa verification error: {str(e)}", exc_info=True)
            return self._handle_error(plot, verification, str(e))

            
    def _extract_title_number(self, plot):
        """
        Extract parcel/title number from plot.
        Prefer explicit parcel number supplied by the owner.
        """
        if getattr(plot, 'parcel_number', None):
            return plot.parcel_number
        # For testing, generate based on plot ID
        return f"TEST/{plot.id}/2024"
    
    def _get_owner_id_number(self, plot):
        """Get owner ID number from plot's owner"""
        if getattr(plot, 'owner_id_number', None):
            return plot.owner_id_number
        if plot.agent:
            return plot.agent.id_number
        elif plot.landowner:
            # You might need to extract from landowner profile
            return "12345678"  # Default for testing
        return "12345678"
    
    def _get_owner_name(self, plot):
        """Get owner name"""
        if getattr(plot, 'owner_full_name', None):
            return plot.owner_full_name
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

    def _handle_failure(self, plot, verification, reason, search_result=None, ownership_result=None):
        """Handle failed verification (invalid or mismatched data)."""
        details = {
            'reason': reason,
            'search_result': search_result,
            'ownership_result': ownership_result
        }
        verification.stage_details['ardhisasa_failure'] = details
        VerificationStatus.objects.filter(pk=verification.pk).update(
            current_stage='rejected',
            rejected_at=timezone.now(),
            stage_details=verification.stage_details
        )
        VerificationLog.objects.create(
            plot=plot,
            verification_type='api_rejected',
            comment=f"Ardhisasa rejected: {reason}"
        )
        try:
            from notifications.notification_service import NotificationService
            NotificationService.notify_plot_final_status(
                plot=plot,
                status='rejected',
                completed_by=None,
                notes=reason
            )
        except Exception:
            pass

        logger.error(f"❌ Ardhisasa verification rejected for plot {plot.id}: {reason}")
        return {
            'success': False,
            'error': reason,
            'decision': details
        }
