from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from listings.models import Plot, PlotImage


class Command(BaseCommand):
    help = "Attach existing files in MEDIA_ROOT/plot_images to a Plot."

    def add_arguments(self, parser):
        parser.add_argument("--plot-id", type=int, help="Plot ID to attach images to.")
        parser.add_argument("--parcel-number", type=str, help="Parcel number to identify plot.")
        parser.add_argument("--latest", type=int, default=5, help="Number of latest files to attach.")

    def handle(self, *args, **options):
        plot_id = options.get("plot_id")
        parcel_number = options.get("parcel_number")
        latest = options.get("latest") or 5

        if not plot_id and not parcel_number:
            raise CommandError("Provide --plot-id or --parcel-number.")

        if plot_id:
            plot = Plot.objects.filter(id=plot_id).first()
        else:
            plot = Plot.objects.filter(parcel_number__iexact=parcel_number).first()

        if not plot:
            raise CommandError("Plot not found.")

        media_root = Path(getattr(settings, "MEDIA_ROOT", "media"))
        images_dir = media_root / "plot_images"
        if not images_dir.exists():
            raise CommandError(f"plot_images directory not found at {images_dir}")

        files = sorted(
            [f for f in images_dir.iterdir() if f.is_file()],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if not files:
            raise CommandError("No files found in plot_images directory.")

        existing_names = set(
            PlotImage.objects.filter(plot=plot).values_list("image", flat=True)
        )
        attached = 0
        for file_path in files[:latest]:
            relative_name = f"plot_images/{file_path.name}"
            if relative_name in existing_names:
                continue
            PlotImage.objects.create(
                plot=plot,
                image=relative_name,
                uploaded_by=None,
            )
            attached += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Attached {attached} image(s) to plot {plot.id} at {timezone.now()}."
            )
        )
