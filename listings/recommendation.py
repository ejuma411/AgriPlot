from decimal import Decimal

from django.db.models import Count, F, Q

from .models import Plot, UserInterest, UserPlotView


class RecommendationService:
    RULE_BASED = "rule_based"
    ML = "ml"

    def __init__(self, strategy=RULE_BASED):
        self.strategy = strategy or self.RULE_BASED

    def recommend_for_user(self, user, limit=6):
        if self.strategy == self.ML:
            return self._ml_recommendations(user, limit=limit)
        return self._rule_based_recommendations(user, limit=limit)

    def _rule_based_recommendations(self, user, limit=6):
        profile = getattr(user, "profile", None)
        interests = UserInterest.objects.filter(user=user).select_related("plot")
        views = UserPlotView.objects.filter(user=user).select_related("plot")

        preferred_counties = list(
            interests.exclude(plot__county__isnull=True)
            .values_list("plot__county", flat=True)
        )
        preferred_land_types = list(
            interests.exclude(plot__land_type__isnull=True)
            .values_list("plot__land_type", flat=True)
        )
        viewed_plot_ids = list(views.values_list("plot_id", flat=True))

        queryset = (
            Plot.objects.filter(is_hidden=False)
            .exclude(market_status="sold")
            .exclude(id__in=viewed_plot_ids)
            .annotate(
                interest_count=Count("buyer_interests", distinct=True),
                view_count=Count("view_events", distinct=True),
            )
        )

        listing_type_filter = Q()
        if profile and profile.intent == "tenant":
            listing_type_filter = Q(listing_type__in=["lease", "both"])
        elif profile and profile.intent == "buyer":
            listing_type_filter = Q(listing_type__in=["sale", "both"])
        elif profile and profile.intent == "farmer":
            listing_type_filter = Q(land_type="agricultural")

        if listing_type_filter:
            queryset = queryset.filter(listing_type_filter)

        if preferred_counties:
            queryset = queryset.annotate(
                county_match=Count("id", filter=Q(county__in=preferred_counties))
            )
        else:
            queryset = queryset.annotate(county_match=Count("id", filter=Q(pk__isnull=False)))

        if preferred_land_types:
            queryset = queryset.annotate(
                land_type_match=Count("id", filter=Q(land_type__in=preferred_land_types))
            )
        else:
            queryset = queryset.annotate(land_type_match=Count("id", filter=Q(pk__isnull=False)))

        return queryset.order_by(
            F("county_match").desc(),
            F("land_type_match").desc(),
            F("interest_count").desc(),
            F("view_count").desc(),
            "-created_at",
        )[:limit]

    def _ml_recommendations(self, user, limit=6):
        return self._rule_based_recommendations(user, limit=limit)

    @staticmethod
    def serialize(plots):
        payload = []
        for plot in plots:
            payload.append(
                {
                    "id": plot.id,
                    "title": plot.title,
                    "county": plot.county,
                    "price": float(plot.price or Decimal("0")),
                    "listing_type": plot.listing_type,
                    "land_type": plot.land_type,
                    "url": plot.get_absolute_url(),
                }
            )
        return payload
