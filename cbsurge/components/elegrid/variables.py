from collections import OrderedDict
import logging


logger = logging.getLogger(__name__)

def generate_variables():
    """
    Generate electricity grid variables dict
    :return:
    """

    variables = OrderedDict()

    license = "Creative Commons BY 4.0"
    attribution = "World Bank Group, University of Oxford"

    for operator in ['sum', 'density']:
        name = operator
        if operator == 'sum':
            name = 'length'
        variables[f'elegrid_{name}'] = dict(
            title=f'Total {name} of electricity grid',
            source='geohub:/api/datasets/310aadaa61ea23811e6ecd75905aaf29',
            operator=operator,
            percentage=True if operator != 'density' else False,
            license=license,
            attribution=attribution,
        )

    return variables