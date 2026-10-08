"""SAM entry point. No Uvicorn server and no durable local-disk state in Lambda."""
import logging

from mangum import Mangum
from .main import app

# Never log the API Gateway event, request headers, or session response bodies.
logging.getLogger("mangum").setLevel(logging.WARNING)
handler = Mangum(app, lifespan="off")
