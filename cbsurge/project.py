import datetime
import io
import os
import click
import logging
import shutil
from rasterio.crs import CRS as rCRS
from pyproj import CRS as pCRS
import rasterio.warp
from osgeo import gdal
import geopandas
import json
import sys
from cbsurge.admin.osm import fetch_admin
from cbsurge.az.fileshare import list_projects, upload_project, download_project
from rich.progress import Progress

logger = logging.getLogger(__name__)
gdal.UseExceptions()


class Project:
    config_file_name = 'rapida.json'
    data_folder_name = 'data'

    _instance = None
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, path: str,polygons: str = None,
                 mask: str = None, projection: str = 'ESRI:54009',
                 comment: str = None, **kwargs ):

        if path is None:
            raise ValueError("Project path cannot be None")

        self.path = os.path.abspath(path)
        self.geopackage_file_name = f"{os.path.basename(self.path)}.gpkg"
        if not polygons:
            self.load_config()  # ✅ Call a function that loads config safely

        else:
            self.name = os.path.basename(self.path)
            self._cfg_ = {
                "name": self.name,
                "path": self.path,
                "config_file": self.config_file,
                "create_command": ' '.join(sys.argv),
                "created_on": datetime.datetime.now().isoformat(),
                "user": os.environ.get('USER', os.environ.get('USERNAME')),
            }
            if mask:
                self._cfg_['mask'] = mask
            if comment:
                self._cfg_['comment'] = comment

            if polygons is not None:
                l = geopandas.list_layers(polygons)
                lnames = l.name.tolist()
                lcount = len(lnames)
                if lcount > 1:
                    click.echo(f'{polygons} contains {lcount} layers: {",".join(lnames)}')
                    layer_name = click.prompt(
                        f'{polygons} contains {lcount} layers: {",".join(lnames)} Please type/select  one or pres enter to skip if you wish to use default value',
                        type=str, default=lnames[0])
                else:
                    layer_name = lnames[0]
                if not os.path.exists(self.data_folder):
                    os.makedirs(self.data_folder)
                gdf = geopandas.read_file(polygons, layer=layer_name, )
                target_crs = pCRS.from_user_input(projection)
                src_crs = gdf.crs

                if not src_crs.is_exact_same(target_crs):
                    rgdf = gdf.to_crs(crs=target_crs)

                cols = rgdf.columns.tolist()
                if not ('h3id' in cols and 'undp_admin_level' in cols):
                    logger.info(f'going to add rapida specific attributes country code')
                    bbox = tuple(gdf.total_bounds)
                    if not src_crs.is_geographic:
                        left, bottom, right, top = bbox
                        bbox = rasterio.warp.transform_bounds(src_crs=rCRS.from_epsg(src_crs.to_epsg()),
                                                              dst_crs=rCRS.from_epsg(4326),
                                                              left=left, bottom=bottom,
                                                              right=right, top=top,

                                                                   )
                    a0_polygons = fetch_admin(bbox=bbox,admin_level=0)
                    a0_gdf = None
                    with io.BytesIO(json.dumps(a0_polygons, indent=2).encode('utf-8') ) as a0l_bio:
                        a0_gdf = geopandas.read_file(a0l_bio).to_crs(crs=target_crs)
                    rgdf_centroids = rgdf.copy()
                    rgdf_centroids["geometry"] = rgdf.centroid
                    jgdf = geopandas.sjoin(rgdf_centroids, a0_gdf, how="left", predicate="within", )
                    jgdf['geometry'] = rgdf['geometry']
                    rgdf = jgdf
                self._cfg_['countries'] = tuple(set(rgdf['iso3']))

                rgdf.to_file(filename=self.geopackage_file_path, driver='GPKG', engine='pyogrio', mode='w', layer='polygons',
                             promote_to_multi=True)


                self.save()

    def load_config(self):
        """Load configuration safely to avoid recursion"""
        try:
            with open(self.config_file, mode="r", encoding="utf-8") as f:
                config_data = json.load(f)
            self.__dict__.update(config_data)  # ✅ Update instance variables safely
            self.is_valid
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Warning: Could not load config file ({self.config_file}): {e}")

    @property
    def data_folder(self):
        return os.path.join(self.path, self.data_folder_name)

    @property
    def config_file(self):
        return os.path.join(self.path, self.config_file_name)

    @property
    def geopackage_file_path(self):
        return os.path.join(self.data_folder, self.geopackage_file_name)

    def __str__(self):
        return json.dumps(
            {"Name": self.name, "Path": self.path, "Valid": self.is_valid}, indent=4
        )

    @property
    def is_valid(self):
        """Conditions for a valid project"""
        return (os.path.exists(self.path) and os.access(self.path, os.W_OK)
                and os.path.exists(self.config_file)) and os.path.getsize(self.config_file) > 0

    def delete(self, force=False):
        if not force and not click.confirm(f'Are you sure you want to delete {self.name} located in {self.path}?',
                                           abort=True):
            return

        shutil.rmtree(self.path)

    def save(self):
        os.makedirs(self.data_folder, exist_ok=True)

        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding="utf-8") as cfgf:
                content = cfgf.read()
                data = json.loads(content) if content else {}
        else:
            data = {}

        data.update(self._cfg_)

        with open(self.config_file, 'w', encoding="utf-8") as cfgf:
            json.dump(data, cfgf, indent=4)


@click.command(no_args_is_help=True)
@click.option('-n', '--name', required=True, type=str,
              help='Name representing a new folder in the current directory' )
@click.option('-p', '--polygons', required=True, type=str,
              help='Full path to the vector polygons dataset in any OGR supported format' )
@click.option('-m', '--mask', required=False, type=str,
              help='Full path to the mask dataset in any GDAL/OGR supported format. Can be vector or raster' )
@click.option('-c', '--comment', required=False, type=str,
              help='Any comment you might want to add into the project config' )

def create(name=None, polygons=None, mask=None, comment=None):
    """
    Create a Rapida project in a new folder

    """
    logger = logging.getLogger('rapida')
    abs_folder = os.path.abspath(name)
    if os.path.exists(abs_folder):
        logger.error(f'Folder "{name}" already exists in {os.getcwd()}')
        sys.exit(1)
    else:
        os.mkdir(abs_folder)

    project = Project(path=abs_folder, polygons=polygons, mask=mask, comment=comment)
    assert project.is_valid
    logger.info(f'Project "{project.name}" was created successfully.')




@click.command(short_help=f'List rapida projects/folders located in default Azure file share')
def list():
    for project_name in list_projects():
        click.echo(project_name)




@click.command()

@click.argument('project_folder', nargs=1 )
@click.option('--max_concurrency', default=4, show_default=True, type=int,
              help=f'The number of threads to use when uploading a file')
@click.option('--overwrite','-o',is_flag=True,default=False, help="Whether to overwrite the project in case it already exists."
)


def upload(project_folder=None,max_concurrency=None,overwrite=None):

    project_folder = os.path.abspath(project_folder)
    assert os.path.exists(project_folder), f'{project_folder} does not exist'


    with Progress() as progress:
        progress.console.print(f'Going to upload {project_folder} to Azure')
        upload_project(project_folder=project_folder, progress=progress, overwrite=overwrite, max_concurrency=max_concurrency)
        progress.console.print(f'Rapida project "{project_folder}" was uploaded successfully to Azure')

@click.command()

@click.argument('name', nargs=1 )
@click.argument('destination_path', type=click.Path())

@click.option('--max_concurrency', default=4, show_default=True, type=int,
              help=f'The number of threads to use when downloading a file')
@click.option('--overwrite','-o',is_flag=True,default=False, help="Whether to overwrite the project in case it already exists locally."
)

def download(name=None, destination_path=None, max_concurrency=None,overwrite=None ):




    with Progress() as progress:
        progress.console.print(f'Going to download rapida project "{name}" from Azure')
        download_project(name=name, dst_folder=destination_path, progress=progress, overwrite=overwrite, max_concurrency=max_concurrency)
        progress.console.print(f'Project "{name}" was downloaded successfully to {os.path.join(destination_path, name)}')

