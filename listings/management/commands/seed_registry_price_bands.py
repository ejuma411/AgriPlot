from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand
from django.utils import timezone

from listings.models import MarketPriceBand
from registry_mock.models import MockLandRegistry


class Command(BaseCommand):
    help = "Seed registry-derived price bands for every mock registry parcel."

    URBAN_COUNTIES = {"Nairobi"}
    PERI_URBAN_COUNTIES = {"Kiambu", "Kajiado", "Machakos", "Mombasa", "Nakuru"}

    BASE_SALE_BANDS = {
        "urban": (Decimal("20000000"), Decimal("80000000")),
        "peri_urban": (Decimal("5000000"), Decimal("20000000")),
        "rural": (Decimal("800000"), Decimal("3000000")),
    }

    LEASE_RATIOS = {
        "urban": Decimal("0.04"),
        "peri_urban": Decimal("0.03"),
        "rural": Decimal("0.02"),
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--active-only",
            action="store_true",
            help="Only generate bands for active registry records with a parcel and owner.",
        )

    def _market_zone_for(self, record):
        county = (record.county or "").strip()
        subcounty = (record.subcounty or "").strip()
        if county in self.URBAN_COUNTIES or "westlands" in subcounty.lower():
            return "urban"
        if county in self.PERI_URBAN_COUNTIES:
            return "peri_urban"
        return "rural"

    def _title_multiplier(self, record):
        # Registry-freehold parcels tend to price stronger than leasehold parcels.
        return Decimal("1.00") if record.land_type == "FREEHOLD" else Decimal("0.92")

    def _encumbrance_multiplier(self, record):
        if record.is_charged and record.has_caution:
            return Decimal("0.80")
        if record.is_charged:
            return Decimal("0.85")
        if record.has_caution:
            return Decimal("0.90")
        return Decimal("1.00")

    def _size_multiplier(self, record):
        acreage = Decimal(str(record.acreage_ha or 0))
        if acreage <= 0:
            return Decimal("1.00")
        # Smaller parcels are often priced at a premium; larger tracts get a modest bulk discount.
        if acreage <= Decimal("1.0"):
            return Decimal("1.10")
        if acreage <= Decimal("3.0"):
            return Decimal("1.00")
        return Decimal("0.92")

    def _round_money(self, value):
        return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _build_band_values(self, record, listing_type, market_zone):
        sale_min, sale_max = self.BASE_SALE_BANDS[market_zone]
        multiplier = self._title_multiplier(record) * self._encumbrance_multiplier(record) * self._size_multiplier(record)

        if listing_type == "sale":
            min_price = self._round_money(sale_min * multiplier)
            max_price = self._round_money(sale_max * multiplier)
        else:
            lease_ratio = self.LEASE_RATIOS[market_zone]
            min_price = self._round_money(sale_min * multiplier * lease_ratio)
            max_price = self._round_money(sale_max * multiplier * lease_ratio)

        return min_price, max_price

    def handle(self, *args, **options):
        today = timezone.now().date()
        records = MockLandRegistry.objects.all().order_by("parcel_number")
        if options["active_only"]:
            records = records.filter(
                parcel_number__isnull=False,
            )

        created = 0
        updated = 0

        for record in records:
            market_zone = self._market_zone_for(record)
            land_type = "agricultural"
            area_unit = "acres"
            band_source = f"Registry parcel {record.parcel_number}"
            band_notes = (
                "Registry-derived pricing guide. "
                f"Conditions used: county={record.county or 'n/a'}, "
                f"subcounty={record.subcounty or 'n/a'}, "
                f"market_zone={market_zone}, "
                f"title={record.land_type}, "
                f"encumbrances={'charged' if record.is_charged else 'clean'}"
                f"{' with caution' if record.has_caution else ''}, "
                f"acreage={record.acreage_ha} ha."
            )

            for listing_type in ("sale", "lease"):
                min_price, max_price = self._build_band_values(record, listing_type, market_zone)
                lookup = {
                    "county": record.county or "",
                    "subcounty": record.subcounty or "",
                    "market_zone": market_zone,
                    "land_type": land_type,
                    "listing_type": listing_type,
                    "area_unit": area_unit,
                    "source": band_source,
                }
                defaults = {
                    "min_price_per_unit": min_price,
                    "max_price_per_unit": max_price,
                    "effective_from": today,
                    "effective_to": None,
                    "is_active": True,
                    "notes": band_notes,
                }
                _, was_created = MarketPriceBand.objects.update_or_create(**lookup, defaults=defaults)
                if was_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Registry price bands processed: {created} created, {updated} updated."
            )
        )
