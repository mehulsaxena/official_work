import json
import os
import environ
import template_runner_api
from template_runner_api.lib.v2 import service

ROOT_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

@environ.config(prefix='')
class ApiConfig:
    postgraphile_url = environ.var()
    redis_hostname = environ.var()
    redis_port = environ.var()
    redis_db = environ.var()
    redis_password = environ.var()
    elasticsearch_host = environ.var()
    elasticsearch_port = environ.var()
    elasticsearch_index = environ.var()
    dcs_server_url = environ.var()
    secrets_config = environ.var()
    root_path = environ.var(default="/naas/template-runner/v1")

    def to_dict(self):
        """
        To dict returns the dictionary configuration in order to pass it to the template runner library
        """

        config = {
            "postgraphile_url": self.postgraphile_url,
            "redis_hostname": self.redis_hostname,
            "redis_port": self.redis_port,
            "redis_db": self.redis_db,
            "redis_password": self.redis_password,
            "elasticsearch_host": self.elasticsearch_host,
            "elasticsearch_port": self.elasticsearch_port,
            "elasticsearch_index": self.elasticsearch_index,
            "dcs_server_url": self.dcs_server_url,
            "secrets_config": self.secrets_config,
        }
        return config



def init_cfg():
    ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
    if 'RUNLOCAL' in os.environ and os.environ['RUNLOCAL'] == "1":
        # Read the local config and stuff all the values in os.environ
        with open(ROOT_DIR + '/local-config.json') as f:
            c = json.loads(f.read())
            for item in c['env']:
                for key in item:
                    os.environ[key] = str(item[key])
    return environ.to_config(ApiConfig)

def init_api():
    cfg = init_cfg()
    template_runner_api.template_runner_api_service = service.TemplateRunnerApiService(config=cfg.to_dict())

