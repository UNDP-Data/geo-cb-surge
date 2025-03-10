# geo-cb-surge
A repo to hold python tools that facilitate the assessment of natural hazards over various domains like population, landuse, infrastructure, etc  

## Installation

Install the project with dependencies to virtual environment as below.

```shell
pipenv run pip install -e .
```

If you want to install optional dependencies for testing and jupyter, execute the following command.

```shell
pipenv run pip install .[dev,jupyter]
```

To uninstall the project from Python environment, execute the following command.

```shell
pipenv run pip uninstall geo-cb-surge
```

## Usage

Then, run the below command to show help menu.

```shell
pipenv run rapida --help
```

## Setup

To access blob storage in Azure, each user must have a role of `Storage Blob Data Contributor`.

- inside Docker container

Since it has an issue of opening browser by azure.identity package inside docker container, use `az login` to authenticate prior to use API.

```shell
az login # authenticate with az login
pipenv run rapida init
```

- without Docker

`init` command will open browser to authenticate to Azure

```shell
pipenv run rapida init
```

## Admin

`admin` command provides functionality to retrieve admin data for passed bounding bbox from either OpenStreetMap or OCHA.

- OSM

```shell
pipenv run rapida admin osm --help
```

- ocha

```shell
pipenv run rapida admin ocha --help
```

## Run test

Each `cbsurge`'s modules has its own test suite which can be ran independently

```shell
make test
```

before running the above command, please use `devcontainer` or `make shell` to enter to docker container first.

## Using docker

### build docker-image

```shell
make build
```

If you would like to build image for production, execute the below command

```shell
PRODUCTION=true make build
```

- launch docker container

```shell
make up
```

You can access to JupyterHub through `http:localhost:8100` in your browser. 

- set users

Authenticate users can be set through `JUPYTER_USERS` variable at `.env` file.

```
cp .env.example .env
vi .env
```

JUPYTER_USERS can have multiple users (username:password) for authentication

```shell
JUPYTER_USERS=docker:docker user:user
```

folder structure in the container will be as follows:

- /data - it will be mounted to fileshare. All files under this folder will be kept
  - /data/{username} - users can explore all users file, a user has no permission to edit other users' folder.
- /home/{username} - user home folder. This data will be lost when the server is restarted.

### destroy docker container

```shell
make down
```

### enter to Docker container

```shell
make shell
pipenv run rapida --help # run CLI in shell on docker container
```

## Authenticate on local machine

You can login to UNDP account in local machine, then mount auth token information to the Docker. Thus, session class will use your local authentication info for the tool.

Firstly, copy `env.example` to create `.env` locally.

Set the following environmental variables.

```shell
TENANT_ID=
CLIENT_ID=
```

`CLIENT_ID` (Use it from Microsoft Azure CLI) can be found [here](https://learn.microsoft.com/en-us/troubleshoot/entra/entra-id/governance/verify-first-party-apps-sign-in#application-ids-of-commonly-used-microsoft-applications).
`TENANT_ID` is for UNDP. Please ask administrator for it.

create new virtual environment in local machine (eg, pipenv), install the following dependencies.

```shell
pip install msal azure-core playwright azure-storage-blob click
```

Execute below py file independently to authenticate in local machine.

```shell
python cbsurge/az/auth.py
```

`python cbsurge/az/auth.py --help` to show usage.

Use `-c {cache_dir}` to change folder path to store `token_cache.json`.

The script will create token_cache.json at `~/cbsurge/token_cache.json`.

Open `docker-compose.yaml`. Uncomment the following code to mount json file from your local to the container.

You may need to adjust file path according to your environment settings.

```yaml
volume:
  - ~/.cbsurge/token_cache.json:/root/.cbsurge/token_cache.json
```

Using the below command to setup rapida tool. If it shows `authentication successful` in the log, it uses credential from your local machine directly.

```shell
rapida init
```