from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = "Run SLA-related maintenance tasks (escalations and reminders)"

    def handle(self, *args, **options):
        self.stdout.write("Running SLA tasks...")
        call_command('escalate_unconfirmed_tasks')
        call_command('send_task_reminders')
        self.stdout.write(self.style.SUCCESS("SLA tasks complete"))
