from collections.abc import Callable

from cuid2 import cuid_wrapper

cuid_generator: Callable[[], str] = cuid_wrapper()


def create_cuid() -> str:
    return cuid_generator()
