from fastapi import FastAPI

from sample.app_factory import app_factory

# from sample.core import configure_logger
from sample.core import configure_logger, settings

configure_logger(settings=settings)

app = FastAPI()


app = app_factory()
