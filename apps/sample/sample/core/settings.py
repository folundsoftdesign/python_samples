"""
This module is used to setup the settings for the application.

The settings are loaded from the following sources in order:
1. Init settings
2. Environment variables
3. .env file
4. Secret files
5. JSON config file

Note that all settings are stored in the config folder.

Also introduces the PYTHON_ENV environment variable which is used to determine the current environment.
The default value is 'development'.

The settings can be accessed as attributes of the settings object.

Example usage:
    settings = Settings()
    print(settings.python_env)
    print(settings.log_level)
    print(settings.TRAFIKVERKET_API_KEY)
    print(settings.is_production())

"""

import os
from enum import StrEnum
from typing import List, Tuple, Type, Union

from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from sample.constants import APP_NAME

CONFIG_FOLDER = "./config"


class PythonEnvEnum(StrEnum):
    local = "local"
    development = "development"
    testing = "testing"
    staging = "staging"
    production = "production"


PYTHON_ENV = os.environ.get("PYTHON_ENV", PythonEnvEnum.development)


class LogLevelEnum(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=f"{CONFIG_FOLDER}/.env",
        env_file_encoding="utf-8",
        json_file=f"{CONFIG_FOLDER}/{PYTHON_ENV}.json",
        json_file_encoding="utf-8",
    )

    # Application settings are defined here (these are the default values and can be overriden in json file, .env file or environment variables)
    python_env: PythonEnvEnum | str = PYTHON_ENV

    log_level: LogLevelEnum = LogLevelEnum.DEBUG
    log_json: bool = False

    mongo_host: Union[str, List[str]] = "localhost"
    mongo_user: str | None = None
    mongo_pass: str | None = None
    mongo_db: str = "sample"
    mongo_auth_db: str | None = None
    mongo_config: str | None = "?ssl=false&readPreference=primary"

    @property
    def app_name(self) -> str:
        return APP_NAME

    @property
    def config_folder(self) -> str:
        return CONFIG_FOLDER

    @property
    def mongo_dsn(self) -> str:
        # Setup authSource - defaults to mongo_db if mongo_auth_db not provided
        authSource = (
            f"&authSource={self.mongo_auth_db}"
            if self.mongo_auth_db
            else f"&authSource={self.mongo_db}"
        )

        if isinstance(self.mongo_host, list):
            hosts = ",".join(self.mongo_host)
        else:
            hosts = self.mongo_host

        if self.mongo_user is None or self.mongo_pass is None:
            return f"mongodb://{hosts}/{self.mongo_db}{self.mongo_config}"

        return f"mongodb://{self.mongo_user}:{self.mongo_pass}@{hosts}{self.mongo_config}{authSource}"

    @property
    def logger_config_file(self) -> str:
        return f"../config/logging_{PYTHON_ENV}.json"

    # Helper methods

    def is_production(self) -> bool:
        return self.python_env == PythonEnvEnum.production

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            JsonConfigSettingsSource(settings_cls),
        )


# Example usage
settings = Settings()
