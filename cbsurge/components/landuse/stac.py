import asyncio
import logging
import os
import re
from glob import glob
from collections import defaultdict
from typing import Dict

from osgeo import gdal
from datetime import datetime, date
from rich.progress import Progress
import pystac_client
import rasterio
from rasterio.warp import reproject, Resampling, calculate_default_transform
from rasterio.enums import Resampling as ResampleEnum
from rasterio.crs import CRS
import httpx
import geopandas as gpd
from cbsurge.util import geo
from cbsurge.util.chunker import chunker

logger = logging.getLogger('rapida')


STAC_MAP = {
    'earth-search': 'https://earth-search.aws.element84.com/v1'
}


def interpolate_stac_source(source: str) -> dict[str, str]:
    """
    Interpolate stac source. Source of stac should be defined like below:

    {stac_id}:{collection_id}:{target band value}

    :param source: stac source
    :return: dist consist of id, collection and value
    """
    parts = source.split(':')
    assert len(parts) == 3, 'Invalid source definition'
    stac_id, collection, target_value = parts
    return {
        'id': stac_id,
        'collection': collection,
        'value': target_value
    }


def create_date_range(target_year: int) -> str:
    """
    create date range from start date to end date for a given target year

    :param target_year: target year
    :return: date range formatted as YYYY-MM-DD/YYYY-MM-DD. But maximum date is always today's date.
    """
    start_date = date(target_year, 1, 1)
    end_of_year = date(target_year, 12, 31)
    today = date.today()

    end_date = min(today, end_of_year)

    return f"{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"


def s3_to_http(url):
    """
    Convert s3 protocol to http protocol

    :param url: URL starts with s3://
    :return http url
    """
    if url.startswith('s3://'):
        s3_path = url
        bucket = s3_path[5:].split('/')[0]
        object_name = '/'.join(s3_path[5:].split('/')[1:])
        return 'https://{0}.s3.amazonaws.com/{1}'.format(bucket, object_name)
    else:
        return url


def harmonize_to_old(data):
    """
    Harmonize new Sentinel-2 data to the old baseline by subtracting a fixed offset.

    described at https://planetarycomputer.microsoft.com/dataset/sentinel-2-l2a#Baseline-Change

    Parameters
    ----------
    data : xarray.DataArray
        A DataArray with dimensions (e.g., time, band, y, x).

    Returns
    -------
    harmonized : xarray.DataArray
        The input data with an offset of 1000 subtracted.
    """
    offset = 1000
    return data - offset


async def download_from_https_async(
        file_url: str,
        target: str,
        target_srs: str,
        no_data_value: int = 0,
        progress=None,
) -> str:
    logging.debug("Starting download: %s", file_url)
    extension = os.path.splitext(file_url)[1]
    download_file = f"{target}.tif"

    if os.path.exists(download_file):
        return download_file

    tmp_file = f"{target}{extension}.tmp"
    pattern = r"/(\d{4})/(\d{1,2})/(\d{1,2})/"
    match = re.search(pattern, file_url)
    if match:
        year, month, day = map(int, match.groups())
        acquisition_date = datetime(year, month, day)
        logging.debug("Extracted acquisition date: %s", acquisition_date)
    else:
        logging.error("Failed to extract date from file_url: %s", file_url)
        raise ValueError(f"Could not extract date from URL: {file_url}")

    cutoff = datetime(2022, 1, 25)
    download_task = None
    if progress is not None:
        download_task = progress.add_task(
            description=f'[blue] Downloading {file_url}', total=None)

    async with httpx.AsyncClient() as client:
        async with client.stream("GET", file_url) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))

            if progress is not None and download_task is not None:
                progress.update(download_task, total=total)

            with open(tmp_file, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    f.write(chunk)
                    if progress is not None and download_task is not None:
                        progress.update(download_task, advance=len(chunk))

    if progress and download_task:
        progress.remove_task(download_task)

    logging.debug("Downloaded %s to %s", file_url, target)

    with rasterio.open(tmp_file) as src:
        data = src.read()
        dst_crs = CRS.from_wkt(target_srs.ExportToWkt())

        if acquisition_date >= cutoff:
            data = harmonize_to_old(data)  # Ensure harmonize_to_old is defined

        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )

        profile = src.profile.copy()
        nodata = profile.get("nodata", no_data_value)
        profile.update({
            "crs": dst_crs,
            "transform": transform,
            "width": width,
            "height": height,
            "driver": "GTiff",
            "compress": "ZSTD",
            "tiled": True,
            "nodata": nodata,
        })

        with rasterio.open(download_file, "w", **profile) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=data[i - 1],
                    destination=rasterio.band(dst, i),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=Resampling.nearest,
                    src_nodata=nodata,
                    dst_nodata=nodata,
                )

    os.remove(tmp_file)
    logging.debug("Downloaded file saved to %s", download_file)
    return download_file


def get_bounds_and_resolution(file_paths):
    bounds = []
    xres_list = []
    yres_list = []

    for fp in file_paths:
        with rasterio.open(fp) as src:
            bounds.append(src.bounds)
            xres, yres = src.res
            xres_list.append(xres)
            yres_list.append(yres)

    left = min(b.left for b in bounds)
    bottom = min(b.bottom for b in bounds)
    right = max(b.right for b in bounds)
    top = max(b.top for b in bounds)

    xRes = min(xres_list)
    yRes = min(yres_list)

    return (left, bottom, right, top), xRes, yRes


def crop_asset_files(base_dir,
                     target_srs,
                     geopackage_file_path,
                     polygons_layer_name,
                     asset_nodata: dict[str, int],
                     progress: Progress = None,):
    """
    Create a VRT for each asset (eg, B02, B03), then crop downloaded data by project area.
    The output file is geotiff file.

    :param base_dir: Root directory for downloaded sentinel data
    :param target_srs: target projection CRS
    :param geopackage_file_path: path to geopackage file
    :param polygons_layer_name: name of layer polygon layer in geopackage to mask
    :param progress: rich progress object
    """
    post_task = None
    if progress is not None:
        post_task = progress.add_task(
            description=f'[red] Postprocessing downloaded data', total=None)

    band_files = defaultdict(list)

    # delete all vrt and tif exists under base_dir
    for fname in os.listdir(base_dir):
        if fname.endswith((".tif", ".vrt", ".xml")):
            path = os.path.join(base_dir, fname)
            if os.path.isfile(path):
                os.remove(path)

    for jp2_path in glob(os.path.join(base_dir, "**", "B??.tif"), recursive=True):
        filename = os.path.basename(jp2_path)
        band_name = os.path.splitext(filename)[0]  # "B02" 部分だけ取る
        band_files[band_name].append(jp2_path)

    # get highest resolution from all bands
    subdirs = [os.path.join(base_dir, d) for d in os.listdir(base_dir)
               if os.path.isdir(os.path.join(base_dir, d))]
    first_subdir = subdirs[0]
    sample_tif_files = glob(os.path.join(first_subdir, "B??.tif"))
    _, xRes, yRes = get_bounds_and_resolution(sample_tif_files)


    output_files = []

    if progress is not None and post_task is not None:
        progress.update(post_task, description=f'[red] Postprocessing...', total=len(band_files))

    for band_name, files in band_files.items():
        if progress is not None and post_task is not None:
            progress.update(post_task, description="[red] Creating VRT...")
        vrt_path = os.path.join(base_dir, f"{band_name}.vrt")
        masked_path = os.path.join(base_dir, f"{band_name}.tif")

        # get maximum bounds from all files
        bounds = get_bounds_and_resolution(files)[0]

        nodata_value = 0
        if asset_nodata is not None and asset_nodata[band_name]:
            nodata_value = asset_nodata[band_name]

        # create VRT with highest resolution
        gdal.BuildVRT(vrt_path, files,
                      outputBounds=bounds,
                      xRes=xRes,
                      yRes=yRes,
                      resampleAlg="nearest",
                      outputSRS=target_srs,
                      srcNodata=nodata_value,
                      VRTNodata=nodata_value,
                      addAlpha=False)

        if progress is not None and post_task is not None:
            progress.update(post_task, description="[red] Cropping VRT...")

        # crop VRT by project area to GeoTiff
        geo.import_raster(
            source=vrt_path, dst=masked_path, target_srs=target_srs,
            x_res=xRes, y_res=yRes,
            crop_ds=geopackage_file_path, crop_layer_name=polygons_layer_name,
            return_handle=False,
            progress=progress,
            warpMemoryLimit=1024,
        )

        if os.path.exists(vrt_path):
            os.remove(vrt_path)

        output_files.append(masked_path)

        if progress is not None and post_task is not None:
            progress.update(post_task, description=f"[red] Processed {band_name}", advance=1)

    if progress and post_task:
        progress.remove_task(post_task)

    return output_files


async def download_stac(
    stac_url: str,
    collection_id: str,
    geopackage_file_path: str,
    polygons_layer_name: str,
    output_dir: str,
    target_year: int,
    target_assets: dict[str, str],
    target_srs,
    progress: Progress = None,
):
    """
    download STAC data from Earth Search to create tiff file for each asset (eg, B02, B03) required

    :param stac_url: STAC root URL
    :param collection_id: collection id
    :param geopackage_file_path: path to geopackage file
    :param polygons_layer_name: name of layer polygon layer in geopackage to mask
    :param output_dir: output directory
    :param target_year: target year
    :param target_assets: target assets.
    :param target_srs: target projection CRS
    :param progress: rich progress object
    :return the list of output files
    """

    stac_task = None
    if progress:
        stac_task = progress.add_task(f"[cyan]Connecting to {stac_url}/{collection_id}", total=None)

    client = pystac_client.Client.open(stac_url)

    df_polygon = gpd.read_file(geopackage_file_path, layer=polygons_layer_name)
    df_polygon.to_crs(epsg=4326, inplace=True)
    bbox = df_polygon.total_bounds

    if progress and stac_task:
        progress.update(stac_task, description="[yellow]Searching for STAC items...")

    datetime = create_date_range(target_year)
    search = client.search(
        collections=[collection_id],
        bbox=bbox,
        query={"eo:cloud_cover": {"lt": 5}},
        datetime=datetime,
    )

    items = list(search.items())
    if progress and stac_task:
        progress.update(stac_task, description=f"[green]Found {len(items)} items.")

    latest_per_tile = {}
    for item in items:
        tile_id = item.properties.get("grid:code")
        if tile_id is None:
            continue

        if tile_id not in latest_per_tile or item.datetime > latest_per_tile[tile_id].datetime:
            if all(asset in item.assets for asset in target_assets):
                latest_per_tile[tile_id] = item

    asset_urls = []
    for item in latest_per_tile.values():
        tile_id = item.properties["grid:code"]
        assets = item.get_assets()
        for key, asset in item.assets.items():
            if key in target_assets:
                asset_meta = assets[key].to_dict()
                band_meta = asset_meta['raster:bands'][0]
                no_data = band_meta['nodata']
                asset_urls.append((asset.href, key, tile_id, no_data))

    if not asset_urls:
        raise RuntimeError(f"No assets found in {stac_url} for target area")

    if progress and stac_task:
        progress.update(stac_task, description=f"[cyan]Preparing to download {len(asset_urls)} assets", total=len(asset_urls))

    asset_nodata = {}
    for chunk in chunker(asset_urls, 5):
        download_tasks = {}
        for url, asset_key, tile_id, nodata in chunk:
            url = s3_to_http(url)
            band_name = target_assets[asset_key]
            asset_nodata[band_name] = nodata
            download_dir = os.path.join(output_dir, tile_id)
            os.makedirs(download_dir, exist_ok=True)

            task = asyncio.create_task(
                download_from_https_async(
                    file_url=url,
                    target=os.path.join(download_dir, band_name),
                    target_srs=target_srs,
                    progress=progress,
                    no_data_value=nodata,
                ),
                name=f"{tile_id}:{band_name}",
            )
            download_tasks[band_name] = task

        done, pending = await asyncio.wait(download_tasks.values(), return_when=asyncio.ALL_COMPLETED)

        for task in done:
            try:
                band_name = task.get_name()
                result = await task
                if progress and stac_task:
                    progress.update(stac_task, description=f"[green]Saved {band_name}", advance=1)
                logging.debug(f"Downloaded {band_name} to {result}")
            except Exception as e:
                band_name = task.get_name()
                logging.error(f"Failed to download {band_name}: {e}")

        for task in pending:
            band_name = task.get_name()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logging.warning(f"Cancelled download for {band_name}")

    if progress and stac_task:
        progress.update(stac_task, description="[magenta]Cropping downloaded assets...")

    output_files = crop_asset_files(
        base_dir=output_dir,
        target_srs=target_srs,
        geopackage_file_path=geopackage_file_path,
        polygons_layer_name=polygons_layer_name,
        asset_nodata=asset_nodata,
        progress=progress,
    )

    if progress and stac_task:
        progress.update(stac_task, description="[bold green]Download and crop complete!")
        progress.remove_task(stac_task)

    return output_files
