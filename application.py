import os
import sys

# Add the directory right above this one to the python include path
# This makes the app easy to run from the command line without being installed
# as a package
import time

from template_runner_api.lib.v2.models import TemplateRunnerRequestTypeEnum

sys.path.append('/'.join(os.path.dirname(os.path.abspath(__file__)).split('/')[:-1]))
from jwt import decode, ExpiredSignatureError
import uvicorn
from config_memory import ConfigMemory
from fastapi import Header, HTTPException, Depends, FastAPI, status

import fastapi
from fastapi.middleware import cors
from fastapi.responses import JSONResponse

from loguru import logger
from template_runner_api import config
from template_runner_api.lib.v2 import models
from template_runner_api.lib.v2.service import TemplateRunnerApiService
from template_runner_api.setup_logging import setup_logging
import urllib3
from device_connection import DeviceConnection

cfg = config.init_cfg()

app = fastapi.FastAPI(
    openapi_url=f"/openapi.json",
    docs_url=f"/docs",
    redoc_url=f"/redoc",
    title="Template Runner",
    description="An openapi microservice to run templates across devices in parallel",
    version="2.0",
)

app.add_middleware(
    cors.CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

jwt_result = None

responses = {
    401: {"description": "Not Authorized"},
    403: {"description": "Token Expired"},
}


def validate_jwt(x_auth_token: str = Header(None)):
    """
    Validate a jwt.

    - **x_auth_token** - The jwt to validate. This comes from the http request headers. e.g. curl -H "x-auth-token: <jwt>"
    """
    try:
        logger.info("START:Validating the JWT")
        jwt_secret = os.environ['JWT_SECRET']
        jwt_audience = os.environ['JWT_AUDIENCE']
        # TODO check to see if i should verify
        decode(str.encode(x_auth_token, 'utf8'), jwt_secret, algorithms=['HS256'], audience=jwt_audience,
               verify=True)
        logger.info("END:Validating the JWT")

    except ExpiredSignatureError as ese:
        logger.error(f"ERROR: JWT has expired {ese}")
        raise HTTPException(status_code=403, detail=f'JWT has expired {ese}')
    except Exception as e:
        logger.error(f"Token is unauthorized {e}")
        raise HTTPException(status_code=401, detail=f'Unauthorized user: {e}')


@app.get(f"/health", status_code=status.HTTP_200_OK)
async def health_check():
    """
    Simple health check. We should spend more time thinking about this.
    """
    logger.info('MSG: Display if API is running!')
    return "OK"


@app.post(path=f"/render-template",
          response_model=models.RenderTemplateResponse,
          responses={**responses,
                     500: {"description": "Internal Server Error", "model": models.RenderTemplateResponse}},
          dependencies=[Depends(validate_jwt)])
def render_template(api_request: models.RenderTemplateRequest, x_auth_token: str = Header(None)):
    """
    Given a list of devices, search for all templates for that device and return the rendered templates.

    Request payload: RenderTemplateRequest
    - **device_list**: A list of DeviceSearch object. Each device will be processed via the method explained above. This may be left empty if a search_criteria is provided instead.
    - **search_criteria**: Criteria specifying device type and location that can be expanded into a list of devices. Either device_list must be set of search_criteria must be set. Both may not be left blank. If both are set, device_list is used.
    - **operation**: A search parameter for finding templates. Options are [ CONFIGPUSH | AUDIT ]
    - **section**: A search parameter for finding templates. The database field for this param is automazione.templates.template_component.
    - **template_overrides**: As part of rendering templates, template variables are lookup from the database. You may override any of those values here.
    - **is_rollback**: Only used for CONFIGPUSH. This will specify is only the reset-cli template should be run.


    Response payload RenderTemplateResponse:
    The basic return stucture will look like this:

    ApiResponse:

      - **status**: An integer return code. A 200 means the call was successful. A 500 means a critical infrastructure error occurred. A 400 means the result was partially successful and you will need to dig through the results to see what went wrong.
      - **render_results**: The results of rendering the templates
    """
    try:
        logger.info('START: render templates')
        service = TemplateRunnerApiService(config=cfg.to_dict())
        _err, api_result = service.render_templates(config=cfg.to_dict(), api_request=api_request)
        logger.info('END: render templates')
        return api_result
    except Exception as e:
        error_msg = f"An unexpected exception occured calling the template runner: {e}"
        logger.error(error_msg)
        return error_msg, 500


@app.post(path=f"/run-template",
          response_model=models.TemplateRunnerApiResponse,
          responses={**responses,
                     500: {"description": "Internal Server Error", "model": models.TemplateRunnerApiResponse}},
          dependencies=[Depends(validate_jwt)])
def run_template(api_request: models.TemplateRunnerApiRequest, x_auth_token: str = Header(None)):
    """
    There are two types of requests this endpoint may run [ TEMPLATE_LOOKUP | SSH_PASSTHRU ]. Given a device list,
    TEMPLATE_LOOKUP will process each device in the device list in parallel, passing the JWT you sent into this request
    via the x_auth_token header on to DCS. DCS will use this JWT to lookup the ssh credentials for each device.

    If you leave the device_list field blank and instead provide a search criteria object, the service will expand
    that search criteria to a device list for you and use that device list.

    The result of TEMPLATE_LOOKUP is a complex object with statuses for each of the many steps taken: looking up all
    templates for a device, rendering them, running the commands for each template on the device and then matching
    the device output against each template's match criteria. This is a lot of data and it gets complex.

    SSH_PASSTHRU is a more minimal call. It will not perform template lookup, rendering or matching. It will run the
    exact list of commands you supply against each device in the device list. You are responsible for passing in the
    ssh credentials in this request. Like TEMPLATE_LOOKUP, if you leave the device list blank and provide a search
    criteria, this service will also expand that search criteria to a device list

    Request payload: TemplateRunnerApiRequest
    - **run_id**: Each device result is written to Kibana. This run_id groups them together. It should be a uuid.
    - **request_type**: [ TEMPLATE_LOOKUP | SSH_PASSTHRU ]
    - **threading_type**: Ignore this legacy parameter. It defaults to multi threaded.
    - **device_list**: A list of DeviceSearch object. Each device will be processed via the method explained above. This may be left empty if a search_criteria is provided instead.
    - **search_criteria**: Criteria specifying device type and location that can be expanded into a list of devices. Either device_list must be set of search_criteria must be set. Both may not be left blank. If both are set, device_list is used.
    - **operation**: A search parameter for finding templates. Options are [ CONFIGPUSH | AUDIT ]
    - **section**: A search parameter for finding templates. The database field for this param is automazione.templates.template_component.
    - **template_overrides**: As part of rendering templates, template variables are lookup from the database. You may override any of those values here.
    - **jwt**: The JWT which has access to the devices in the device list.
    - **use_jwt_from_header**: If you do not specify a JWT in the payload, the one you used for this call will be used.
    - **device_commands**: Only used for SSH_PASSTHRU. Specify the exact list of commands to send to the devices.
    - **device_username**: Only used for SSH_PASSTHRU. Specify the ssh username for all the devices in the device list.
    - **device_password**: Only used for SSH_PASSTHRU. Specify the ssh password (in clear text BOO!) for all the devices in the device list.
    - **is_rollback**: Only used for TEMPLATE_LOOKUP when the operation is CONFIGPUSH. This will specify is only the reset-cli template should be run.
    - **debug_kv**: DEPRECATED. This is from the old ST2 days.
    - **threading_count**: You may specify the maximum number of threads to be used at one time if you know what you are doing.

    Response payload TemplateRunnerApiResponse:
    The basic return stucture will look like this:

    ApiResponse:

      - **status**: An integer return code. A 200 means the call was successful. A 500 means a critical infrastructure error occurred. A 400 means the result was partially successful and you will need to dig through the results to see what went wrong.
      - **run_id**: The run_id from the request. Provided for convenience to lookup device results in Kibana
      - **result**: A complex object with several layers of statuses for the looking up templates, rendering them etc.
      - **operation**: The operation parameter from the request. I don't know why this is here.
      - **section**: The section parameter from the request. I don't know why this is here.
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
            return str(_err), 500

        # Leave this here to debug pydantic errors
        real_result = models.TemplateRunnerApiResponse(**result.dict())
        return real_result
    except Exception as e:
        error_msg = f"An unexpected exception occured calling the template runner: {e}"
        logger.error(error_msg)
        return error_msg, 500


@app.on_event("startup")
async def startup():
    cfg = config.init_cfg()
    service = TemplateRunnerApiService(config=cfg.to_dict())
    my_dict = cfg.to_dict()
    my_dict['redis_password'] = "REDACTED"  # nosec
    logger.debug(my_dict)
    ConfigMemory.set("APP_SERVICE", service)


if __name__ == "__main__":

    app_port = 8080
    if "RUNLOCAL" in os.environ and os.environ["RUNLOCAL"] == "1":
        app_port = 8000

    # AO - 28 Sept 2020 - Working with John and Alan. We moved this here because it has to be done
    # once per process
    # DCS uses signals. Those signals do not work in a multithreaded environment. The try catch is to override this
    # error - JDM 2019-01-10
    try:
        dcs = urllib3.util.parse_url(cfg.dcs_server_url)
        dcs_host = dcs[2]
        dcs_port = dcs[3]
        DeviceConnection.set_server(server_ip=dcs_host, server_port=dcs_port)
    except Exception as e:
        raise e

    # This port must remain 8080 or the health check will fail when deployed to k8s
    # uvicorn.run(app, host="0.0.0.0", port=app_port, root_path=cfg.root_path)

    # need to instantiate uvicorn server first in order to setup logging interceptor next
    # NOTE: the ENV var LOGURU_LEVEL controls the logging levels
    log_level = os.getenv("LOGURU_LEVEL", "INFO").lower()
    uv_server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",  # nosec¬
            port=app_port,
            log_level=log_level,
            root_path=cfg.root_path
        )
    )

    # now we setup logging and its interceptors
    setup_logging()
    logger.debug("Starting the uvicorn server...")
    logger.info({"password": "secret"})
    # the uvicorn logger will be intercepted at this point and can now run
    uv_server.run()

