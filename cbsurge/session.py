import logging
import os
import json
from azure.identity import DefaultAzureCredential, AzureAuthorityHosts
from azure.core.exceptions import ClientAuthenticationError
from azure.storage.blob.aio import BlobServiceClient, ContainerClient
from azure.storage.fileshare.aio import ShareServiceClient


logger = logging.getLogger(__name__)


class Session(object):
    def __init__(self):
        """
        constructor
        """
        self.config = self.get_config()
        if self.config is not None:
            logger.debug(f"config was loaded: {self.config}")


    def __enter__(self):
        return self


    def __exit__(self, exc_type, exc_value, traceback):
        pass


    def get_config_file_path(self) -> str:
        user_dir = os.path.expanduser("~")
        config_file_path = os.path.join(user_dir, ".cbsurge", "config.json")
        return config_file_path


    def get_config(self):
        """
        get config from ~/.cbsurge/config.json

        Returns:
            JSON object
        """
        config_file_path = self.get_config_file_path()
        if os.path.exists(config_file_path):
            with open(config_file_path, "r", encoding="utf-8") as data:
                return json.load(data)
        else:
            return None

    def get_config_value_by_key(self, key: str, default=None):
        """
        get config value by key

        Parameters:
            key (str): key
            default (str): default value if not exists. Default is None
        """
        if self.config is None:
            self.config = self.get_config()
        if self.config is not None:
            return self.config.get(key, default)
        else:
            return default


    def set_config_value_by_key(self, key: str, value):
        if self.config is None:
            self.config = {}
        self.config[key] = value


    def set_root_data_folder(self, folder_name):
        self.set_config_value_by_key("root_data_folder", folder_name)

    def get_root_data_folder(self, is_absolute_path=True):
        """
        get root data folder

        Parameters:
            is_absolute_path (bool): Optional. If true, return absolute path, otherwise relative path. Default is True.
        Returns:
            root data folder path (str)
        """
        root_data_folder = self.get_config_value_by_key("root_data_folder")
        if is_absolute_path:
            return  os.path.expanduser(root_data_folder)
        else:
            return root_data_folder

    def set_account_name(self, account_name: str):
        self.set_config_value_by_key("account_name", account_name)

    def get_account_name(self):
        return self.get_config_value_by_key("account_name")

    def set_container_name(self, container_name: str):
        self.set_config_value_by_key("container_name", container_name)

    def get_container_name(self):
        return self.get_config_value_by_key("container_name")

    def set_file_share_name(self, file_share_name: str):
        self.set_config_value_by_key("file_share_name", file_share_name)

    def get_file_share_name(self):
        return self.get_config_value_by_key("file_share_name")

    def save_config(self):
        """
        Save config.json under user directory as ~/.cbsurge/config.json
        """
        if self.get_root_data_folder() is None:
            raise RuntimeError(f"root_data_folder is not set")
        if self.get_account_name() is None:
            raise RuntimeError(f"account_name is not set")
        if self.get_container_name() is None:
            raise RuntimeError(f"container_name is not set")
        if self.get_file_share_name() is None:
            raise RuntimeError(f"file_share_name is not set")

        config_file_path = self.get_config_file_path()

        dir_path = os.path.dirname(config_file_path)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

        with open(config_file_path, "w", encoding="utf-8") as file:
            json.dump(self.config, file, ensure_ascii=False, indent=4)

        logger.debug(f"config file was saved to {config_file_path}")


    def get_credential(self):
        """
        get token credential for azure.

        Usage example:

        from azure.storage.blob import BlobServiceClient
        from cbsurge.session import Session

        session = Session()
        credential = session.get_credential()

        blob_service_client = BlobServiceClient(
            account_url="https://<my_account_name>.blob.core.windows.net",
            credential=token_credential
        )

        Returns:
            Azure TokenCredential is returned if authenticated.
        """
        credential = DefaultAzureCredential()
        return credential


    def get_token(self, scopes = "https://storage.azure.com/.default"):
        """
        get access token for blob storage account. This token is required for using Azure REST API.

        Parameters:
            scopes: scopes for get_token method. Default to "https://storage.azure.com/.default"
        Returns:
            Azure token is returned if authenticated.
        Raises:
            ClientAuthenticationError is raised if authentication failed.

            ClientAuthenticationError:
            https://learn.microsoft.com/en-us/python/api/azure-core/azure.core.exceptions.clientauthenticationerror?view=azure-python
        """
        try:
            credential = self.get_credential()
            token = credential.get_token(scopes)
            return token
        except ClientAuthenticationError as err:
            logger.error("authentication failed. Please use 'rapida init' command to setup credentials.")
            raise err


    def authenticate(self, scopes = "https://storage.azure.com/.default"):
        """
        Authenticate to Azure through interactive browser if DefaultAzureCredential is not provideds.
        Authentication uses DefaultAzureCredential.

        Please refer to https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential?view=azure-python
        about DefaultAzureCredential api specificaiton.

        Parameters:
            scopes: scopes for get_token method. Default to "https://storage.azure.com/.default"
        Returns:
            Azure credential and token are returned if authenticated. If authentication failed, return None.
        """
        try:
            credential = DefaultAzureCredential(
                exclude_interactive_browser_credential=False,
            )
            token = credential.get_token(scopes)
            return [credential, token]
        except ClientAuthenticationError as err:
            logger.error("authentication failed.")
            logger.error(err)
            return None


    def get_blob_service_client(self, account_name: str = None) -> BlobServiceClient:
        """
        get BlobServiceClient for account url

        If the parameter is not set, use default account name from config.

        Usage example:
            with Session() as session:
                blob_service_client = session.get_blob_service_client(
                    account_name="undpgeohub"
                )

        Parameters:
            account_name (str): name of storage account. https://{account_name}.blob.core.windows.net
        Returns:
            BlobServiceClient
        """
        credential = self.get_credential()
        account_url = self.get_blob_service_account_url(account_name)
        blob_service_client = BlobServiceClient(
            account_url=account_url,
            credential=credential
        )
        return blob_service_client

    def get_blob_container_client(self, account_name: str = None, container_name: str = None) -> ContainerClient:
        """
        get ContainerClient for account name and container name

        If the parameter is not set, use default account name from config.

        Parameters:
            account_name (str): name of storage account. https://{account_name}.blob.core.windows.net
            container_name (str): name of storage container name. https://{account_name}.blob.core.windows.net/{container_name}
        Returns:
            ContainerClient
        """
        blob_service_client = self.get_blob_service_client(account_name)
        ct_name = container_name if container_name is not None else self.get_container_name()
        container_client = blob_service_client.get_container_client(ct_name)
        return container_client

    def get_blob_service_account_url(self, account_name: str = None) -> str:
        """
        get blob service account URL

        If the parameter is not set, use default account name from config.

        Parameters:
            account_name (str): Optional. name of storage account url.
        """
        ac_name = account_name if account_name is not None else self.get_account_name()
        return f"https://{ac_name}.blob.core.windows.net"

    def get_share_service_client(self, account_name: str = None, share_name: str = None) -> ShareServiceClient:
        """
        get ShareServiceClient for account url

        If the parameter is not set, use default account name from config.

        Usage example:
            with Session() as session:
                share_service_client = session.get_share_service_client(
                    account_name="undpgeohub",
                    share_name="cbrapida"
                )

        Parameters:
            account_name (str): name of storage account.
            share_name (str): name of file share.

            both parameters are equivalent to the below URL's bracket places.

            https://{account_name}.file.core.windows.net/{share_name}
        Returns:
            ShareServiceClient
        """
        credential = self.get_credential()
        account_url = self.get_share_service_account_url(account_name, share_name)
        share_service_client = ShareServiceClient(
            account_url=account_url,
            credential=credential
        )
        return share_service_client

    def get_file_share_account_url(self, account_name: str = None, share_name: str = None) -> str:
        """
        get blob service account URL

        If the parameter is not set, use default account name from config.

        Parameters:
            account_name (str): Optional. name of storage account url. If the parameter is not set, use default account name from config.
            share_name (str): name of file share. If the parameter is not set, use default account name from config.
        """
        ac_name = account_name if account_name is not None else self.get_account_name()
        sh_name = share_name if share_name is not None else self.get_file_share_name()
        return f"https://{ac_name}.file.core.windows.net/{sh_name}"