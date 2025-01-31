
import os.path
import asyncio
from sympy.parsing.sympy_parser import parse_expr
from pydantic import BaseModel, FilePath
from typing import Optional, List, Union
import re
from cbsurge.stats.zst import zonal_stats, sumup
from cbsurge.session import Session
from cbsurge import util
import logging
from cbsurge.az import blobstorage



logger = logging.getLogger(__name__)



class SurgeVariable(BaseModel):
    name: str
    title: str
    source: Optional[str] = None
    sources: Optional[Union[List[str], str]] = None
    variables: Optional[List[str]] = None
    local_path: FilePath = None
    component: str = None
    _extractor_: str = r"\{([^}]+)\}"
    _default_operators_ = '+-/*%'
    _source_folder_: str = None

    def __init__(self, **kwargs):
        """
        Initialize the object with the provided arguments.
        """
        super().__init__(**kwargs)

        try:
            parsed_expr = parse_expr(self.sources)
            self.variables = [s.name for s in parsed_expr.free_symbols]

        except (SyntaxError, AttributeError):
            pass
        with Session() as s:
            root_folder = s.get_root_data_folder()
            self._source_folder_ = os.path.join(root_folder, self.component, self.name)


    def __str__(self):
        """
        String representation of the class.
        """
        return f'{self.__class__.__name__} {self.model_dump_json(indent=2)}'

    def download(self, **kwargs):


            src_path = self.interpolate(template=self.source, **kwargs)
            if os.path.exists(self.local_path): return self.local_path
            downloaded_file = asyncio.run(blobstorage.download_blob(src_path=src_path,dst_path=self.local_path)                             )
            assert downloaded_file == self.local_path, f'The local_path differs from {downloaded_file}'
            return downloaded_file

    def compute(self, **kwargs):
        pass

    def resolve(self, **kwargs):

        with Session() as s:
            src_rasters = list()
            vars_ops = list()
            for var in self.variables:
                var_dict = s.get_variable(component=self.component, variable=var)
                v = self.__class__(name=var, component=self.component, **var_dict)
                p = v(**kwargs) # resolve
                logger.info(f'{var} was resolved to {p}')
                src_rasters.append(p)
                vars_ops.append((var, 'sum'))

            gdf = zonal_stats(src_rasters=src_rasters,src_vector=kwargs['admin'], vars_ops=vars_ops)
            expr = f'{self.name}={self.sources}'
            gdf.eval(expr, inplace=True)
            gdf.to_file(f'/tmp/popstats.fgb', driver='FlatGeobuf',index=False,engine='pyogrio')

    def __call__(self, force_compute=False, **kwargs):

            if self.source:
                if not os.path.exists(self._source_folder_):
                    os.makedirs(self._source_folder_)
                src_path = self.interpolate(template=self.source, **kwargs)
                _, file_name = os.path.split(src_path)
                self.local_path = os.path.join(self._source_folder_, file_name)
                if os.path.exists(self.local_path):
                    #os.remove(self.local_path)
                    return self.local_path

            # first try to download from source
            if self.source and not force_compute:
                return self.download(**kwargs)
            # use sources to compute
            if self.sources:
                if self.variables:
                    logger.info(f'Going to compute {self.name} from {self.sources}')
                    assert 'admin' in kwargs, f'Admin layer is required to compute zonal stats'
                    return self.resolve(**kwargs)

                else:
                    logger.info(f'Going to sum up {self.name} from source files')\
                    # interpolate templates
                    source_blobs = list()
                    for source_template in self.sources:
                        source_file_path = self.interpolate(template=source_template, **kwargs)
                        source_blobs.append(source_file_path)
                    downloaded_files = asyncio.run(
                        blobstorage.download_blobs(src_blobs=source_blobs, dst_folder=self._source_folder_,
                                                   progress=kwargs['progress'])
                    )
                    assert len(self.sources) == len(downloaded_files), f'Not all sources were downloaded for {self.name} variable'
                    sumup(src_rasters=downloaded_files,dst_raster=self.local_path)
                    logger.info(f'{self.local_path} was created for variable {self.name}')




    def interpolate(self, template=None, **kwargs):
        """
        Resolve file paths with the provided kwargs, ensuring that the necessary variables are included.
        """
        if 'country' in kwargs:
            kwargs['country_lower'] = kwargs['country'].lower()
        template_vars = set(re.findall(self._extractor_, template))
        for template_var in template_vars:
            assert template_var in kwargs, f'"{template_var}"  is required to generate source files'
        return template.format(**kwargs)




if __name__ == '__main__':
    logger = util.setup_logger(name='rapida', level=logging.INFO)
    admin_layer = '/data/adhoc/MDA/adm/adm3transn.fgb'
    from rich.progress import Progress

    with Session() as ses:

            popvars = ses.config['variables']['population']
            fk = list(popvars.keys())[0]
            fv = popvars[fk]
            d = popvars



            with Progress(disable=False) as progress:
                total_task = progress.add_task(
                    description=f'[red]Going to process {len(d)} variables', total=len(d))
                for var_name, var_data in d.items():
                    progress.update(task_id=total_task, advance=1, description=f'Processing {var_name}')
                    v = SurgeVariable(name=var_name, component='population', **var_data)
                    r = v(year=2020, country='MDA', force_compute=False, admin=admin_layer, progress=progress)


                progress.remove_task(total_task)


