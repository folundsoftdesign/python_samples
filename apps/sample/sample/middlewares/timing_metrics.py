import logging
import resource
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.datastructures import MutableHeaders

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("timing_metrics")


# try:
#     import pynvml

#     pynvml.nvmlInit()
#     gpu_available = True
# except ImportError:
#     gpu_available = False


@dataclass
class TimingMetricsMiddleware:
    app: "ASGIApp"
    header_name_process_time: str = "X-Process-Time"
    header_name_gpu_utilization: str = "X-GPU-Utilization"
    header_name_cpu_time_used: str = "X-CPU-Time-Used"

    async def __call__(self, scope: "Scope", receive: "Receive", send: "Send") -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        start_time, start_cpu_time, start_gpu_util = self._start_metrics()

        async def handle_outgoing_request(message: "Message") -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                self._append_metrics(headers, start_time, start_cpu_time, start_gpu_util)
            await send(message)

        await self.app(scope, receive, handle_outgoing_request)

    def _start_metrics(self):
        start_time = time.time()
        start_cpu_time = resource.getrusage(resource.RUSAGE_SELF).ru_utime
        start_gpu_util = None
        # if gpu_available:
        #     handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        #     start_gpu_util = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
        return start_time, start_cpu_time, start_gpu_util

    def _append_metrics(self, headers, start_time, start_cpu_time, start_gpu_util):
        process_time = time.time() - start_time
        cpu_time_used = resource.getrusage(resource.RUSAGE_SELF).ru_utime - start_cpu_time

        # if gpu_available and start_gpu_util is not None:
        #     handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        #     end_gpu_util = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
        #     gpu_utilization = end_gpu_util - start_gpu_util
        #     headers.append(self.header_name_gpu_utilization, str(gpu_utilization))

        headers.append(self.header_name_process_time, str(process_time))
        headers.append(self.header_name_cpu_time_used, str(cpu_time_used))
