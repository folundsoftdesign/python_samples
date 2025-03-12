import logging

import anyio

logging.basicConfig(level=logging.DEBUG)


async def inner_task(cancel_scope: anyio.CancelScope):
    for i in range(3):
        # with cancel_scope: # remove this line
        await anyio.sleep(1)
        logging.debug(f"Inner task: {i}")


async def outer_task():
    with anyio.CancelScope() as cancel_scope:
        for _ in range(2):
            try:
                await inner_task(cancel_scope)
            except anyio.get_cancelled_exc_class():
                logging.debug("Outer task cancelled")
                return


async def main():
    try:
        await outer_task()
    except anyio.get_cancelled_exc_class():
        logging.debug("Main task cancelled")


if __name__ == "__main__":
    anyio.run(main)
