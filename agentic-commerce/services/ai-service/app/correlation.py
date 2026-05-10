"""FastAPI middleware that propagates x-correlation-id."""
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from .logger import set_correlation_id

CORRELATION_HEADER = "x-correlation-id"
REQUEST_HEADER = "x-request-id"


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get(CORRELATION_HEADER) or str(uuid.uuid4())
        request_id = str(uuid.uuid4())

        set_correlation_id(correlation_id)
        request.state.correlation_id = correlation_id
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[CORRELATION_HEADER] = correlation_id
        response.headers[REQUEST_HEADER] = request_id
        return response
