# management/commands/fix_verification_status.py
from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from listings.models import Plot, VerificationStatus
from django.utils import timezone

class Command(BaseCommand):
    help = 'Add verification status to plots missing it'

    def handle(self, *args, **options):
        content_type = ContentType.objects.get_for_model(Plot)
        
        # Get all plots
        plots = Plot.objects.all()
        fixed_count = 0
        
        for plot in plots:
            # Check if verification status exists
            exists = VerificationStatus.objects.filter(
                content_type=content_type,
                object_id=plot.id
            ).exists()
            
            if not exists:
                # Create verification status
                VerificationStatus.objects.create(
                    content_type=content_type,
                    object_id=plot.id,
                    current_stage='pending',
                    document_uploaded_at=timezone.now()
                )
                fixed_count += 1
                self.stdout.write(f"Added verification status to plot {plot.id}: {plot.title}")
        
        self.stdout.write(self.style.SUCCESS(f"Successfully added verification status to {fixed_count} plots"))