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
from typing import Annotated, Any, List, Literal, Tuple, Type, Union

from pydantic import AnyUrl, BeforeValidator, EmailStr, computed_field, model_validator
from pydantic_core import MultiHostUrl
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


PYTHON_ENV = os.environ.get("PYTHON_ENV", PythonEnvEnum.local)


class LogLevelEnum(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",")]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


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

    # MongoDB settings for Beanie
    mongo_host: Union[str, List[str]] = "localhost"
    mongo_user: str | None = None
    mongo_pass: str | None = None
    mongo_db: str = "sample"
    mongo_auth_db: str | None = None
    mongo_config: str | None = "?ssl=false&readPreference=primary"

    frontend_host: str = "http://localhost:7000"
    backend_cors_origins: Annotated[list[AnyUrl] | str, BeforeValidator(parse_cors)] = []

    # SMTP settings
    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: EmailStr | None = None

    DATABASE_TYPE: Literal["postgresql", "sqlite"] = "sqlite"

    POSTGRES_SERVER: str | None = None
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str | None = None
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    SQLALCHEMY_DATABASE_FILE: str = "./data/sample.db"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.backend_cors_origins] + [self.frontend_host]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def app_name(self) -> str:
        return APP_NAME

    @computed_field  # type: ignore[prop-decorator]
    @property
    def config_folder(self) -> str:
        return CONFIG_FOLDER

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_database_uri(self) -> MultiHostUrl | str:
        if self.DATABASE_TYPE == "sqlite":
            return f"sqlite:///{self.SQLALCHEMY_DATABASE_FILE}"

        return MultiHostUrl.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mongo_dsn(self) -> str:
        # Setup authSource - defaults to mongo_db if mongo_auth_db not provided
        auth_source = f"&authSource={self.mongo_auth_db}" if self.mongo_auth_db else f"&authSource={self.mongo_db}"

        if isinstance(self.mongo_host, list):
            hosts = ",".join(self.mongo_host)
        else:
            hosts = self.mongo_host

        if self.mongo_user is None or self.mongo_pass is None:
            return f"mongodb://{hosts}/{self.mongo_db}{self.mongo_config}"

        return f"mongodb://{self.mongo_user}:{self.mongo_pass}@{hosts}{self.mongo_config}{auth_source}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def logger_config_file(self) -> str:
        return f"../config/logging_{PYTHON_ENV}.json"

    # Helper methods
    def is_production(self) -> bool:
        return self.python_env == PythonEnvEnum.production

    # Customise sources
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

    @model_validator(mode="before")
    def check_database_settings(self, values):
        database_type = values.get("DATABASE_TYPE")
        if database_type == "postgresql":
            required_fields = ["POSTGRES_SERVER", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"]
            for field in required_fields:
                if not values.get(field):
                    raise ValueError(f"{field} must be set when DATABASE_TYPE is 'postgresql'")
        elif database_type == "sqlite":
            if not values.get("SQLALCHEMY_DATABASE_FILE"):
                raise ValueError("SQLALCHEMY_DATABASE_FILE must be set when DATABASE_TYPE is 'sqlite'")
        return values


# Example usage
settings = Settings()
