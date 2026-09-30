"""
Management command to migrate all existing complaint ticket IDs from legacy formats
(e.g., GCC-2026-DEMO-142, GCC-2026-473006) to the new standardized format:
DPIG-YYYY-LLL-NNNNNN (e.g., DPIG-2026-GCC-000001, DPIG-2026-GCC-555555).
"""
import re
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from core.models import Complaint, YearlyTicketSequence, generate_ticket_number


class Command(BaseCommand):
    help = "Migrate existing complaints to new ticket ID format: DPIG-YYYY-LLL-NNNNNN"

    def handle(self, *args, **options):
        pattern = re.compile(r"^DPIG-\d{4}-[A-Z0-9]+-\d{6}$")

        non_conforming = Complaint.objects.exclude(ticket_number__regex=r"^DPIG-\d{4}-[A-Z0-9]+-\d{6}$").order_by('created_at', 'id')
        total_count = non_conforming.count()
        self.stdout.write(f"Found {total_count} complaints with legacy ticket formats...")

        if total_count == 0:
            self.stdout.write(self.style.SUCCESS("All complaints already follow the DPIG-YYYY-LLL-NNNNNN format!"))
            return

        migrated = 0
        with transaction.atomic():
            for c in non_conforming:
                old_ticket = c.ticket_number
                year = c.created_at.year if c.created_at else timezone.now().year
                new_ticket = generate_ticket_number(cluster=c.cluster, year=year)

                # Ensure existing audit blocks preserve the ticket number they were originally hashed with
                for log in c.audit_logs.all():
                    if not log.ticket_number:
                        log.ticket_number = old_ticket
                        log.save(update_fields=['ticket_number'])

                c.ticket_number = new_ticket
                c.save(update_fields=['ticket_number'])

                # Append a valid audit block recording the migration transition
                c.create_audit_block(
                    action="TICKET_FORMAT_MIGRATED",
                    performed_by=None,
                    actor_role="SYSTEM_MIGRATION",
                    details={"legacy_ticket": old_ticket, "standardized_ticket": new_ticket}
                )

                self.stdout.write(f"  {old_ticket} -> {new_ticket}")
                migrated += 1

        self.stdout.write(self.style.SUCCESS(f"Successfully migrated {migrated} complaints to DPIG-YYYY-LLL-NNNNNN format."))
