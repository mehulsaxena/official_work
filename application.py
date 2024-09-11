import os
import sys
import time
from jwt import decode, ExpiredSignatureError
import uvicorn
from config_memory import ConfigMemory
from fastapi import Header, HTTPException, Depends, FastAPI, status
from fastapi.middleware import cors
from fastapi.responses import JSONResponse
from loguru import logger
from template_runner_api import config
from template_runner_api.lib.v2 import models
from template_runner_api.lib.v2.service import TemplateRunnerApiService
from template_runner_api.setup_logging import setup_logging
import urllib3
from device_connection import DeviceConnection

# Add the directory right above this one to the python include path
sys.path.append('/'.join(os.path.dirname(os.path.abspath(__file__)).split('/')[:-1]))

# Initialize configuration
cfg = config.init_cfg()

# Create FastAPI app instance
app = FastAPI(
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    title="Template Runner",
    description="An OpenAPI microservice to run templates across devices in parallel",
    version="2.0",
)

# Configure CORS middleware
app.add_middleware(
    cors.CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# JWT validation function
def validate_jwt(x_auth_token: str = Header(None)):
    """
    Validate a JWT provided in the HTTP headers.
    
    Args:
        x_auth_token (str): The JWT to validate.

    Raises:
        HTTPException: If the JWT is expired or invalid.
    """
    try:
        logger.info("START: Validating the JWT")
        jwt_secret = os.environ['JWT_SECRET']
        jwt_audience = os.environ['JWT_AUDIENCE']
        decode(x_auth_token.encode('utf8'), jwt_secret, algorithms=['HS256'], audience=jwt_audience, verify=True)
        logger.info("END: Validating the JWT")
    except ExpiredSignatureError as ese:
        logger.error(f"ERROR: JWT has expired {ese}")
        raise HTTPException(status_code=403, detail=f'JWT has expired {ese}')
    except Exception as e:
        logger.error(f"Token is unauthorized {e}")
        raise HTTPException(status_code=401, detail=f'Unauthorized user: {e}')

# Health check endpoint
@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """
    Simple health check endpoint.
    
    Returns:
        str: Returns "OK" to indicate the API is running.
    """
    logger.info('MSG: Display if API is running!')
    return "OK"

# Endpoint to render templates
@app.post("/render-template", response_model=models.RenderTemplateResponse,
          responses={**{401: {"description": "Not Authorized"}, 403: {"description": "Token Expired"}},
                     500: {"description": "Internal Server Error", "model": models.RenderTemplateResponse}},
          dependencies=[Depends(validate_jwt)])
def render_template(api_request: models.RenderTemplateRequest, x_auth_token: str = Header(None)):
    """
    Render templates based on the provided request.

    Args:
        api_request (RenderTemplateRequest): The request payload.
        x_auth_token (str): The JWT from the headers.

    Returns:
        RenderTemplateResponse: The response with the rendered templates.
    """
    try:
        logger.info('START: Render templates')
        service = TemplateRunnerApiService(config=cfg.to_dict())
        _err, api_result = service.render_templates(config=cfg.to_dict(), api_request=api_request)
        logger.info('END: Render templates')
        return api_result
    except Exception as e:
        error_msg = f"An unexpected exception occurred: {e}"
        logger.error(error_msg)
        return JSONResponse(content={"error": error_msg}, status_code=500)

# Endpoint to run templates
@app.post("/run-template", response_model=models.TemplateRunnerApiResponse,
          responses={**{401: {"description": "Not Authorized"}, 403: {"description": "Token Expired"}},
                     500: {"description": "Internal Server Error", "model": models.TemplateRunnerApiResponse}},
          dependencies=[Depends(validate_jwt)])
def run_template(api_request: models.TemplateRunnerApiRequest, x_auth_token: str = Header(None)):
    """
    Run a template based on the provided request.

    Args:
        api_request (TemplateRunnerApiRequest): The request payload.
        x_auth_token (str): The JWT from the headers.

    Returns:
        TemplateRunnerApiResponse: The response with the status and result.
    """
    try:
        if api_request.request_type == TemplateRunnerRequestTypeEnum.TEMPLATE_LOOKUP:
            api_request.jwt = x_auth_token
        else:
            if not api_request.device_username:
                api_request.jwt = x_auth_token
        service = TemplateRunnerApiService(config=cfg.to_dict())
        _err, result = service.run_templates(api_request=api_request)
        if _err:
            return JSONResponse(content={"error": str(_err)}, status_code=500)

        real_result = models.TemplateRunnerApiResponse(**result.dict())
        return real_result
    except Exception as e:
        error_msg = f"An unexpected exception occurred: {e}"
        logger.error(error_msg)
        return JSONResponse(content={"error": error_msg}, status_code=500)

# Startup event
@app.on_event("startup")
async def startup():
    """
    Initialize the service and configuration at startup.
    """
    cfg = config.init_cfg()
    service = TemplateRunnerApiService(config=cfg.to_dict())
    my_dict = cfg.to_dict()
    my_dict['redis_password'] = "REDACTED"  # nosec
    logger.debug(my_dict)
    ConfigMemory.set("APP_SERVICE", service)

# Main entry point for the application
if __name__ == "__main__":
    app_port = 8080
    if "RUNLOCAL" in os.environ and os.environ["RUNLOCAL"] == "1":
        app_port = 8000

    # Initialize device connection
    try:
        dcs = urllib3.util.parse_url(cfg.dcs_server_url)
        dcs_host = dcs[2]
        dcs_port = dcs[3]
        DeviceConnection.set_server(server_ip=dcs_host, server_port=dcs_port)
    except Exception as e:
        raise e

    # Set up Uvicorn server with logging
    log_level = os.getenv("LOGURU_LEVEL", "INFO").lower()
    uv_server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",
            port=app_port,
            log_level=log_level,
            root_path=cfg.root_path
        )
    )

    setup_logging()
    logger.debug("Starting the Uvicorn server...")
    logger.info({"password": "secret"})  # This should be removed or replaced with a safer practice
    uv_server.run()
