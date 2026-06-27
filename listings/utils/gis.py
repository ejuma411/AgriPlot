'''Utility functions for GIS operations within the AgriPlot Connect application.

This module provides common helpers for calculating distances between
geometries and retrieving nearby amenities for a given Plot instance.
It has been rewritten to use standard math functions (Haversine formula)
instead of Django's built-in GIS support.
''' 

import math
from django.db.models import F
from django.db.models.functions import ACos, Cos, Radians, Sin

def distance_between_coords(lat1, lon1, lat2, lon2) -> float:
    """Return the distance in meters between two sets of coordinates using the Haversine formula."""
    if any(coord is None for coord in (lat1, lon1, lat2, lon2)):
        return 0.0
        
    R = 6371000  # Radius of earth in meters
    lat1, lon1, lat2, lon2 = map(math.radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
    
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    return R * c

def distance_between_points(p1, p2) -> float:
    """Legacy wrapper for old Point objects. Replace with distance_between_coords."""
    raise DeprecationWarning("distance_between_points is deprecated. Use distance_between_coords instead.")

def get_nearest_amenities(plot, amenity_model, limit: int = 5):
    """Return a queryset of the nearest ``amenity_model`` objects to ``plot``.

    Parameters
    ----------
    plot: Plot instance – must have ``latitude`` and ``longitude``.
    amenity_model: Django model class – must have ``latitude`` and ``longitude``.
    limit: Maximum number of results to return (default 5).
    """
    if not plot.latitude or not plot.longitude:
        return amenity_model.objects.none()
        
    if not hasattr(amenity_model, "latitude") or not hasattr(amenity_model, "longitude"):
        raise AttributeError(
            f"{amenity_model.__name__} does not have 'latitude' and 'longitude' fields"
        )
        
    # Convert plot coordinates to radians for DB calculation
    plot_lat = math.radians(float(plot.latitude))
    plot_lon = math.radians(float(plot.longitude))
    
    # 6371000 is Earth radius in meters
    from django.db.models import ExpressionWrapper, FloatField
    qs = (
        amenity_model.objects.filter(latitude__isnull=False, longitude__isnull=False)
        .annotate(
            distance=ExpressionWrapper(
                6371000.0 * ACos(
                    Cos(Radians(plot_lat)) * Cos(Radians('latitude')) * Cos(Radians('longitude') - plot_lon) +
                    Sin(Radians(plot_lat)) * Sin(Radians('latitude'))
                ),
                output_field=FloatField()
            )
        )
        .order_by("distance")[:limit]
    )
    return qs

class DummyDistance:
    """A dummy class to replace django.contrib.gis.measure.D"""
    def __init__(self, **kwargs):
        self.m = kwargs.get('m', 0)
        self.km = kwargs.get('km', 0)
        if self.km:
            self.m = self.km * 1000

Distance = DummyDistance
