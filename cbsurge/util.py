import httpx
import logging
from osgeo import gdal, osr
import itertools
import click
import os
from rich.logging import RichHandler
logger = logging.getLogger(__name__)


def validate_azure_storage_path(a_path:str|None = None):
    assert a_path.startswith(
        'az:'), f'The source blob path {a_path} is not in the correct format: az:account_name:blob_path'
    assert a_path.count(
        ':') == 2, f'The source blob path {a_path} is not in the correct format: az:account_name:blob_path'


def silence_httpx_az():
    #azlogger = logging.getLogger('az.core.pipeline.policies.http_logging_policy')
    azlogger = logging.getLogger('azure')
    azlogger.setLevel(logging.WARNING)
    httpx_logger = logging.getLogger('httpx')
    httpx_logger.setLevel(logging.WARNING)


def chunker(iterable, size):
    it = iter(iterable)
    while True:
        chunk = tuple(itertools.islice(it, size))
        if not chunk:
            break
        yield chunk


def gen_blocks_bbox(ds=None,blockxsize=None, blockysize=None, xminc=None, yminr=None, xmaxc=None, ymaxr=None ):
    """
    Generate reading block for gdal ReadAsArray limited by a bbox
    """


    width = ds.RasterXSize
    height = ds.RasterXSize
    wi = list(range(0, width, blockxsize))
    if width % blockxsize != 0:
        wi += [width]
    hi = list(range(0, height, blockysize))
    if height % blockysize != 0:
        hi += [height]
    for col_start, col_end in zip(wi[:-1], wi[1:]):
        col_size = col_end - col_start
        if  xminc > col_end or xmaxc < col_start:continue
        if col_start < xminc:col_start = xminc
        if col_start+col_size>xmaxc:col_size=xmaxc-col_start
        for row_start, row_end in zip(hi[:-1], hi[1:]):
            if yminr > row_end or ymaxr < row_start :continue
            if row_start<yminr:row_start=yminr
            row_size = row_end - row_start
            if row_start+row_size>ymaxr:row_size= ymaxr-row_start
            yield col_start, row_start, col_size, row_size



def gen_blocks(blockxsize=None, blockysize=None, width=None, height=None ):
    """
    Generate reading block for gdal ReadAsArray
    """
    wi = list(range(0, width, blockxsize))
    if width % blockxsize != 0:
        wi += [width]
    hi = list(range(0, height, blockysize))
    if height % blockysize != 0:
        hi += [height]
    for col_start, col_end in zip(wi[:-1], wi[1:]):
        col_size = col_end - col_start
        for row_start, row_end in zip(hi[:-1], hi[1:]):
            row_size = row_end - row_start
            yield col_start, row_start, col_size, row_size

def fetch_drivers():
    d = dict()
    for i in range(gdal.GetDriverCount()):

        drv = gdal.GetDriver(i)
        d[drv.ShortName] = drv.GetMetadataItem(gdal.DMD_EXTENSIONS)
    return d

def http_get_json(url=None, timeout=None):
    """
    Generic HTTP get function using httpx
    :param url: str, the url to be fetched
    :param timeout: httpx.Timeout instance
    :return: python dict representing the result as parsed json
    """
    assert timeout is not None, f'Invalid timeout={timeout}'
    with httpx.Client(timeout=timeout) as client:
        response = client.get(url)
        response.raise_for_status()
        if response.status_code == 200:
            return response.json()

def http_post_json(url=None, data=None, timeout=None):
    """
    Generic HTTP get function using httpx
    :param url: str, the url to be fetched
    :param timeout: httpx.Timeout instance
    :return: python dict representing the result as parsed json
    """
    assert timeout is not None, f'Invalid timeout={timeout}'
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, data={"data": data})
        response.raise_for_status()
        return response.json()

def validate(url=None, timeout=10):
    """
    Generic HTTP get function using httpx
    :param url: str, the url to be fetched
    :param timeout: httpx.Timeout instance
    :return: python dict representing the result as parsed json
    """
    with httpx.Client(timeout=timeout) as client:
        response = client.head(url, timeout=timeout)
        response.raise_for_status()

def proj_are_equal(src_srs: osr.SpatialReference = None, dst_srs: osr.SpatialReference = None):
    """
    Decides if two projections are equal
    @param src_srs:  the source projection
    @param dst_srs: the dst projection
    @return: bool, True if the source  is different then dst else false
    If the src is ESPG:4326 or EPSG:3857  returns  False
    """
    auth_code_func_name = ".".join(
        [osr.SpatialReference.GetAuthorityCode.__module__, osr.SpatialReference.GetAuthorityCode.__name__])
    is_same_func_name = ".".join([osr.SpatialReference.IsSame.__module__, osr.SpatialReference.IsSame.__name__])
    try:
        proj_are_equal = int(src_srs.GetAuthorityCode(None)) == int(dst_srs.GetAuthorityCode(None))
    except Exception as evpe:
        logger.error(
            f'Failed to compare src and dst projections using {auth_code_func_name}. Trying using {is_same_func_name}')
        try:
            proj_are_equal = bool(src_srs.IsSame(dst_srs))
        except Exception as evpe1:
            logger.error(
                f'Failed to compare src and dst projections using {is_same_func_name}. Error is \n {evpe1}')
            raise evpe1

    return proj_are_equal

def generator_length(gen):
    """
    compute the no of elems inside a generator
    :param gen:
    :return:
    """
    gen1, gen2 = itertools.tee(gen)
    length = sum(1 for _ in gen1)  # Consume the duplicate
    return length, gen2  # Return the length and the unconsumed generator


class BboxParamType(click.ParamType):
    name = "bbox"
    def convert(self, value, param, ctx):
        try:
            bbox = tuple([float(x.strip()) for x in value.split(",")])
            fail = False
        except ValueError:  # ValueError raised when passing non-numbers to float()
            fail = True

        if fail or len(bbox) != 4:
            self.fail(
                f"bbox must be 4 floating point numbers separated by commas. Got '{value}'"
            )

        return bbox

def validate_path(src_path=None):
    assert os.path.isabs(src_path), f'{src_path} has to be a file'
    out_folder, file_name = os.path.split(src_path)
    assert os.path.exists(out_folder), f'Folder {src_path} has to exist'

    if os.path.exists(src_path):
        assert os.access(src_path, os.W_OK), f'Can not write to {src_path}'

class CustomStreamHandler(logging.StreamHandler):
  """Handler that controls the writing of the newline character"""

  special_code = '[!n]'
  active = False
  def emit(self, record) -> None:

    if self.special_code in record.msg:
      record.msg = record.msg.replace( self.special_code, '' )
      self.terminator = ''
      if not self.active:
        self.active = True
      self.stream.write('\r')
      self.flush()
    else:
        self.terminator = '\n'
        if self.active:
            self.stream.write(self.terminator)
            self.flush()
        self.active = False
    try:
        msg = self.format(record)
        # issue 35046: merged two stream.writes into one.
        self.stream.write(msg + self.terminator)
        self.flush()
    except RecursionError:  # See issue 36272
        raise
    except Exception:
        self.handleError(record)

def setup_logger(name=None, make_root=True,  level=logging.INFO):

    if make_root:
        logger = logging.getLogger()

    else:
        logger = logging.getLogger(name)
    formatter = logging.Formatter(
        "%(filename)s:%(funcName)s:%(lineno)d:%(levelname)s:%(message)s",
        "%Y-%m-%d %H:%M:%S",
    )
    logging_stream_handler = RichHandler(rich_tracebacks=True)
    #logging_stream_handler.setFormatter(formatter)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.addHandler(logging_stream_handler)
    logger.name = name
    silence_httpx_az()
    return logger