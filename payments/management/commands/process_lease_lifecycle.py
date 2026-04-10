from django.core.management.base import BaseCommand

from payments.lease_lifecycle import process_lease_lifecycle


class Command(BaseCommand):
    help = "Process lease expiry, 90-day waitlist notices, and next-tenant availability updates."

    def handle(self, *args, **options):
        stats = process_lease_lifecycle()
        self.stdout.write(
            self.style.SUCCESS(
                "Lease lifecycle processed: "
                f"{stats['lease_count']} active leases scanned, "
                f"{stats['tenant_renewal_reminders']} tenant renewal reminders sent, "
                f"{stats['notice_contacts']} queue notices sent, "
                f"{stats['leases_released']} leases released."
            )
        )
