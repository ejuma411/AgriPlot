'''Utility functions for GIS operations within the AgriPlot Connect application.

This module provides common helpers for calculating distances between
geometries and retrieving nearby amenities for a given Plot instance.
It leverages Django's built‑in GIS support (PostGIS) via the `geos` and
`measure` utilities.
''' 

from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D  # Distance


def distance_between_points(p1: Point, p2: Point) -> float:
    """Return the distance in meters between two ``Point`` objects.

    The function uses the ``distance`` method provided by GEOS which
    returns the Euclidean distance in the coordinate system units. Since
    we store geometries using SRID 4326 (WGS84 latitude/longitude), we
    first transform them to the Web Mercator projection (SRID 3857) which
    uses meters as units for accurate distance measurement.
    """
    if not isinstance(p1, Point) or not isinstance(p2, Point):
        raise TypeError("Both arguments must be django.contrib.gis.geos.Point instances")
    # Transform to a metric projection for reliable distance measurement.
    p1_metric = p1.transform(3857, clone=True)
    p2_metric = p2.transform(3857, clone=True)
    return p1_metric.distance(p2_metric)


def get_nearest_amenities(plot, amenity_model, limit: int = 5):
    """Return a queryset of the nearest ``amenity_model`` objects to ``plot``.

    Parameters
    ----------
    plot: Plot instance – must have a ``geom`` ``PointField``.
    amenity_model: Django model class – must have a ``location`` ``PointField``.
    limit: Maximum number of results to return (default 5).

    The function performs a spatial query using ``distance`` annotation and
    orders the results by proximity. It gracefully handles the case where a
    ``geom`` is missing by returning an empty queryset.
    """
    if not hasattr(plot, "geom") or plot.geom is None:
        return amenity_model.objects.none()
    # Ensure the amenity model has a ``location`` field.
    if not hasattr(amenity_model, "location"):
        raise AttributeError(
            f"{amenity_model.__name__} does not have a 'location' PointField"
        )
    # Annotate each amenity with its distance to the plot geometry.
    qs = (
        amenity_model.objects.filter(location__isnull=False)
        .annotate(distance=Distance("location", plot.geom))
        .order_by("distance")[:limit]
    )
    return qs

# Helper alias used elsewhere in the codebase.
Distance = D
