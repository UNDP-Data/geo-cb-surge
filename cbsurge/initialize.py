import logging
import click
import os
import shutil

from requests import session

from cbsurge.session import Session
from cbsurge.components.population.variables import generate_variables as gen_pop_vars


logger = logging.getLogger(__name__)


def setup_prompt(session: Session):
    credential, token = session.authenticate()
    logger.debug(token)
    if token is None:
        click.prompt("Authentication failed.Please `az login` to authenticate first.")
        return

    click.echo("Authentication successful. We need more information to setup from you.")

    # project root data folder
    root_data_folder = None
    absolute_root_data_folder = None
    while not(root_data_folder is not None and os.path.exists(absolute_root_data_folder)):
        data_folder = click.prompt("Please enter project root folder to store all data. Enter to skip if use default value", default="~/cbsurge")
        absolute_root_data_folder = os.path.expanduser(data_folder)

        if os.path.exists(absolute_root_data_folder):
            if click.confirm("The folder already exists. Yes to overwrite, No/Enter to use existing folder", default=False):
                shutil.rmtree(absolute_root_data_folder)
                click.echo(f"Removed folder {absolute_root_data_folder}")
                os.makedirs(absolute_root_data_folder)
                click.echo(f"The project root folder was created at {absolute_root_data_folder}")
                root_data_folder = data_folder
            else:
                click.echo(f"Use {absolute_root_data_folder} as the root folder.")
                root_data_folder = data_folder
        else:
            os.makedirs(absolute_root_data_folder)
            click.echo(f"The project root folder was created at {absolute_root_data_folder}")
            root_data_folder = data_folder
    session.set_root_data_folder(root_data_folder)

    # azure blob container setting
    account_name = click.prompt('Please enter account name for UNDP Azure. Enter to skip if use default value',
                                type=str, default='undpgeohub')
    session.set_account_name(account_name)
    click.echo(f"account name: {account_name}")

    publish_container_name = click.prompt('Please enter UNDP Azure container name of publishing project outcome. Enter to skip if use default value',
                                  type=str, default='rapida')
    session.set_publish_container_name(publish_container_name)
    click.echo(f"publish container name: {publish_container_name}")

    stac_container_name = click.prompt('Please enter container name for UNDP Azure STAC. Enter to skip if use default value',
                                  type=str, default='stacdata')
    session.set_stac_container_name(stac_container_name)
    click.echo(f"stac container name: {stac_container_name}")

    # azure file share setting
    share_name = click.prompt('Please enter share name for UNDP Azure. Enter to skip if use default value',
                              type=str, default='cbrapida')
    session.set_file_share_name(share_name)
    click.echo(f"file share name: {share_name}")


    session.save_config()
    vars_dict = {
        "variables": {
            "population":  gen_pop_vars()
        }
    }
    session.config.update(vars_dict)
    session.save_config()
    click.echo('Setting up was successfully done!')


@click.command()
@click.option('--debug',
              is_flag=True,
              default=False,
              help="Set log level to debug"
              )
def init(debug=False):
    """ Initialize rapida tool"""

    click.echo("Welcome to rapida CLI tool!")
    with Session() as session:
        config = session.get_config()
        if config:
            if click.confirm('Your setup has already been done. Would you like to do setup again?', abort=True):
                setup_prompt(session)
        else:
            if click.confirm('Would you like to setup rapida tool?', abort=True):
                setup_prompt(session)
