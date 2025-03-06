import atexit
import json
import logging.config

from .settings import Settings, settings

logger = logging.getLogger(settings.app_name)


def configure_logger(settings: Settings) -> None:
    config_folder = settings.config_folder

    config_file = f"{config_folder}/logger_stdout.json"

    if settings.log_json:
        config_file = f"{config_folder}/logger_json.json"

    with open(config_file) as f_in:
        config = json.load(f_in)

    logging.config.dictConfig(config)

    queue_handler = logging.getHandlerByName("queue")

    if queue_handler is not None:
        queue_handler.listener.start()  # type: ignore
        atexit.register(queue_handler.listener.stop)  # type: ignore
