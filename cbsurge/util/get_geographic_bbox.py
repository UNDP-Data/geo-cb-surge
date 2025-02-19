import logging

from osgeo import osr

logger = logging.getLogger(__name__)

def get_geographic_bbox(layer):
    # Get the layer's spatial reference
    source_srs = layer.GetSpatialRef()
    min_x, max_x, min_y, max_y = layer.GetExtent(True)
    # If the layer is already in geographic (WGS 84), no reprojection is needed
    if source_srs is None or source_srs.IsGeographic():
        return min_x, min_y, max_x, max_y
    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(4326)
    # Otherwise, perform reprojection to WGS 84 (EPSG:4326)
    transform = osr.CoordinateTransformation(
        source_srs, target_srs
    )


    lat_min, lon_min, lat_max, lon_max = transform.TransformBounds(min_x, min_y, max_x, max_y, 21)

    return lon_min, lat_min, lon_max, lat_max