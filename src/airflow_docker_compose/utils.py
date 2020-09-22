import functools
import toml
import pkg_resources
import os

_package = "airflow_docker_compose"


class UserError(Exception):
    """Raise to send a user consumable message.
    """


@functools.lru_cache()
def get_config():
    if not os.path.exists("pyproject.toml"):
        raise UserError("Missing pyproject.toml file.")

    with open("pyproject.toml", "r") as f:
        config = toml.load(f)

    try:
        return config["tool"]["airflow-docker-compose"]
    except KeyError:
        raise UserError("pyproject.toml file missing a '[tool.airflow-docker-compose]' section.")


def get_airflow_cfg_location():
    return pkg_resources.resource_filename(package, "airflow.cfg")
