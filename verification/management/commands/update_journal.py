from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Auto-update system construction journal from git commits and migrations."

    def handle(self, *args, **options):
        data_file = Path(settings.BASE_DIR) / "verification" / "data" / "system_construction_journal.json"
        data_file.parent.mkdir(parents=True, exist_ok=True)

        entries = []
        if data_file.exists():
            try:
                entries = json.loads(data_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.stderr.write(self.style.ERROR("Journal file is not valid JSON."))
                return

        existing_keys = set()
        for entry in entries:
            existing_keys.add((entry.get("evidence"), entry.get("work_done")))

        max_date = None
        for entry in entries:
            try:
                d = datetime.strptime(entry.get("date", ""), "%Y-%m-%d").date()
                if not max_date or d > max_date:
                    max_date = d
            except ValueError:
                continue

        added = 0

        # Add migration entries
        migrations_dir = Path(settings.BASE_DIR) / "listings" / "migrations"
        if migrations_dir.exists():
            for mig in sorted(migrations_dir.glob("*.py")):
                if mig.name == "__init__.py":
                    continue
                evidence = f"listings/migrations/{mig.name}"
                work_done = f"Added migration {mig.name}"
                key = (evidence, work_done)
                if key in existing_keys:
                    continue
                mtime = datetime.fromtimestamp(mig.stat().st_mtime).date().isoformat()
                entries.append(
                    {
                        "date": mtime,
                        "module": "DB migration",
                        "work_done": work_done,
                        "evidence": evidence,
                        "status": "Done",
                        "next_step": "Apply migrations in target environment",
                    }
                )
                existing_keys.add(key)
                added += 1

        # Add git commit entries
        git_dir = Path(settings.BASE_DIR) / ".git"
        if git_dir.exists():
            since_arg = []
            if max_date:
                since_arg = [f"--since={max_date.isoformat()}"]
            try:
                result = subprocess.run(
                    ["git", "log", "--pretty=format:%H|%ad|%s", "--date=short", *since_arg],
                    cwd=settings.BASE_DIR,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                for line in result.stdout.splitlines():
                    parts = line.split("|", 2)
                    if len(parts) != 3:
                        continue
                    commit_hash, commit_date, subject = parts
                    evidence = f"git:{commit_hash}"
                    work_done = subject.strip()
                    key = (evidence, work_done)
                    if key in existing_keys:
                        continue
                    entries.append(
                        {
                            "date": commit_date,
                            "module": "Code changes (git)",
                            "work_done": work_done,
                            "evidence": evidence,
                            "status": "Done",
                            "next_step": "Review for documentation updates",
                        }
                    )
                    existing_keys.add(key)
                    added += 1
            except (subprocess.CalledProcessError, FileNotFoundError):
                self.stderr.write(self.style.WARNING("Git log unavailable; skipped commit entries."))

        if added == 0:
            self.stdout.write(self.style.SUCCESS("No new journal entries found."))
        else:
            data_file.write_text(json.dumps(entries, indent=2), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Added {added} journal entries."))
