import contextlib
import enum
import functools
import io
import json
import os
import subprocess
import sys
import time

import click
import docker
import pkg_resources
import toml
from compose.cli.command import project_from_options
from compose.cli.main import TopLevelCommand
from dotenv import load_dotenv

from airflow_docker_compose import test


class UserError(Exception):
    """Raise to send a user consumable message.
    """


@functools.lru_cache()
def open_config():
    if not os.path.exists("pyproject.toml"):
        raise UserError("Missing pyproject.toml file.")

    with open("pyproject.toml", "r") as f:
        config = toml.load(f)

    try:
        return config["tool"]["airflow-docker-compose"]
    except KeyError:
        raise UserError("pyproject.toml file missing a '[tool.airflow-docker-compose]' section.")


def construct_airflow_environment(inline=False):
    airflow_vars = open_config().get("airflow-environment-variables")
    if not airflow_vars:
        return ""

    result = ""
    if not inline:
        result += "environment:\n"
    for i, (var, value) in enumerate(airflow_vars.items()):
        result += "{prefix}- {var}={value}".format(
            var=var, value=value, prefix="    " if not inline or i != 0 else ""
        )
    return result


def ensure_network(docker_client):
    docker_network = open_config()["docker-network"]

    print(">>> Creating {} if it does not exist".format(docker_network))
    network_names = {network.name for network in docker_client.networks.list()}

    if docker_network not in network_names:
        docker_client.networks.create(docker_network, check_duplicate=True)


def docker_reset(docker_compose):
    print(">>> Bringing any existing airflow instance down and removing any volumes")

    docker_compose.down({"--volumes": True, "--rmi": "local", "--remove-orphans": True})
    docker_compose.rm({"SERVICE": []})


class ContainerStates(enum.Enum):
    Exist = "exist"
    NotExist = "notexist"


def wait_for_container(docker_client, service=None, label=None, expect=1, to=ContainerStates.Exist):
    while True:
        filters = {}
        if service:
            filters["name"] = service
        if label:
            filters["label"] = label

        containers = docker_client.containers.list(all=False, filters=filters)
        unique_containers = {c.name.rsplit("_", 1)[0] for c in containers}

        if to == ContainerStates.NotExist:
            if len(unique_containers) == 0:
                break

        if to == ContainerStates.Exist:
            if len(unique_containers) == expect:
                break

        print(".", end="")
        sys.stdout.flush()
        time.sleep(1)
    print()


def docker_start(docker_client, docker_compose):
    config = open_config()

    print(">>> Bringing the metadata database up and sleeping to let postgres start")

    docker_compose.up(
        {
            "--detach": True,
            "--no-deps": False,
            "--always-recreate-deps": False,
            "--abort-on-container-exit": False,
            "--remove-orphans": False,
            "--no-recreate": False,
            "--force-recreate": False,
            "--build": False,
            "--no-build": False,
            "--scale": [],
            "SERVICE": ["metadata-db"],
        }
    )
    wait_for_container(docker_client, "metadata-db")

    print(">>> Initializing Metadata Database")
    docker_compose.run(
        {
            "--quiet": True,
            "--detach": True,
            "--name": None,
            "--no-deps": False,
            "--publish": [],
            "--rm": True,
            "--service-ports": False,
            "--use-aliases": False,
            "--user": None,
            "--volume": [],
            "--label": ["dbinit"],
            "--workdir": None,
            "-T": False,
            "-e": ["AIRFLOW__CORE__DAGS_FOLDER=/tmp"],
            "SERVICE": "airflow-web",
            "COMMAND": "initdb",
            "ARGS": [],
        }
    )
    wait_for_container(docker_client, label="dbinit", to=ContainerStates.NotExist)

    with open("tmp-variables.json", mode="wb") as f:
        variables = config.get("default-variables", {})
        f.write(json.dumps(variables, indent=4, sort_keys=True).encode("utf-8"))

    load_variables(docker_client, docker_compose, "tmp-variables.json")

    print(">>> Creating an admin user")
    docker_compose.run(
        {
            "--quiet": True,
            "--detach": True,
            "--name": None,
            "--no-deps": False,
            "--publish": [],
            "--rm": True,
            "--service-ports": False,
            "--use-aliases": False,
            "--user": None,
            "--volume": [],
            "--workdir": None,
            "--label": ["createadmin"],
            "-T": False,
            "-e": ["AIRFLOW__CORE__DAGS_FOLDER=/tmp"],
            "SERVICE": "airflow-web",
            "COMMAND": "create_user",
            "ARGS": [
                "-r",
                "Admin",
                "-u",
                "admin",
                "-p",
                "admin",
                "-e",
                "admin@localhost.com",
                "-f",
                "admin",
                "-l",
                "admin",
            ],
        }
    )
    wait_for_container(docker_client, label="createadmin", to=ContainerStates.NotExist)

    print(">>> Bringing airflow webserver online. The webserver may do some setup...")
    docker_compose.up(
        {
            "--detach": True,
            "--no-deps": False,
            "--always-recreate-deps": False,
            "--abort-on-container-exit": False,
            "--remove-orphans": False,
            "--no-recreate": False,
            "--force-recreate": False,
            "--build": False,
            "--no-build": False,
            "--scale": [],
            "--label": [config["docker-network"]],
            "SERVICE": ["airflow-web"],
        }
    )

    docker_compose.logs(
        {
            "--follow": False,
            "--no-color": False,
            "--tail": None,
            "--timestamps": False,
            "SERVICE": ["airflow-web"],
        }
    )

    print(">>> Bringing the scheduler, worker, and flower online")
    docker_compose.up(
        {
            "--detach": True,
            "--no-deps": False,
            "--always-recreate-deps": False,
            "--abort-on-container-exit": False,
            "--remove-orphans": False,
            "--no-recreate": False,
            "--force-recreate": False,
            "--build": False,
            "--no-build": False,
            "--scale": [],
            "SERVICE": [],
        }
    )

    print(
        ">>> You can now browse to the airflow UI and view the airflow workers:\n\n"
        "                 Airflow UI: http://localhost:30000\n"
        "                   Username: admin\n"
        "                   Password: admin\n\n"
        "                  Flower UI: http://localhost:30001\n\n"
        "              Tail the logs: airflow-docker-compose run logs -f\n"
    )


def load_variables(docker_client, docker_compose, file):
    print(">>> Setting up some variables in the airflow variables metadata database")
    docker_compose.run(
        {
            "--quiet": True,
            "--detach": True,
            "--name": None,
            "--no-deps": False,
            "--publish": [],
            "--rm": True,
            "--service-ports": False,
            "--use-aliases": False,
            "--user": None,
            "--workdir": None,
            "--label": ["initvariables"],
            "-T": False,
            "--volume": ["{file}:/tmp/variables.json".format(file=file)],
            "-e": ["AIRFLOW__CORE__DAGS_FOLDER=/tmp"],
            "SERVICE": "airflow-web",
            "COMMAND": "variables",
            "ARGS": ["-i", "/tmp/variables.json"],
        }
    )
    wait_for_container(docker_client, label="initvariables", to=ContainerStates.NotExist)


def create_cli(docker_client):
    @click.group(help="Run all the airflow management commands.")
    def cli():
        pass

    @cli.command("up")
    @click.argument("service")
    @click.option("--env", default="prod")
    def up(service, env):
        docker_compose = DockerCompose(env=env)

        ensure_network(docker_client)

        services = []
        if service:
            services.append(service)

        docker_compose.up(
            {
                "--detach": True,
                "--no-deps": False,
                "--always-recreate-deps": False,
                "--abort-on-container-exit": False,
                "--remove-orphans": False,
                "--no-recreate": False,
                "--force-recreate": False,
                "--build": False,
                "--no-build": False,
                "--scale": [],
            }
        )

    @cli.command("reset")
    @click.option("--env", default="prod")
    def reset(env):
        docker_compose = DockerCompose(env=env)

        ensure_network(docker_client)
        docker_reset(docker_compose)
        docker_start(docker_client, docker_compose)

    @cli.command("start")
    @click.option("--env", default="prod")
    def start(env):
        docker_compose = DockerCompose(env=env)
        ensure_network(docker_client)
        docker_start(docker_client, docker_compose)

    @cli.command("run")
    @click.argument("command", nargs=1)
    @click.argument("args", nargs=-1)
    def run(command, args):
        ensure_network(docker_client)
        subprocess.call(["docker-compose", "-f", "tmp-docker-compose.yml", command, *args])

    @cli.command("test")
    @click.option("--dag-dir", default=".")
    @click.option("--airflowdocker-tag", default="latest")
    @click.option("--extra-test-dir", default="tests")
    def _test(dag_dir, airflowdocker_tag, extra_test_dir):
        test.test_dag(
            docker_client, dag_dir=dag_dir, tag=airflowdocker_tag, extra_test_dir=extra_test_dir
        )

    @cli.group("variables")
    def variables():
        pass

    @variables.command("load")
    @click.argument("file")
    def variables_load(file):
        docker_compose = DockerCompose()
        load_variables(docker_client, docker_compose, file)

    return cli


class DockerCompose:
    def __init__(self, env="prod"):
        self.env = env

        self.has_created_docker_compose = False
        self.docker_compose_client = None

    @functools.lru_cache()
    def create_docker_compose(self):
        compose_template = pkg_resources.resource_filename(
            "airflow_docker_compose", "docker-compose-template.yml"
        )

        airflow_config_location = pkg_resources.resource_filename(
            "airflow_docker_compose", "airflow.cfg"
        )

        config = open_config()

        docker_network = config["docker-network"]
        with open(compose_template, "rb") as f:
            data = f.read().decode("utf-8")

        airflow_dags_location = os.path.abspath(config.get("dags-folder", "./dags"))
        airflowdocker_tag = config.get("airflowdocker-tag", "latest")

        result = (
            data.replace("{docker_network}", docker_network)
            .replace("{airflow_config_location}", airflow_config_location)
            .replace("{airflow_environment}", construct_airflow_environment())
            .replace("{airflow_environment_inline}", construct_airflow_environment(inline=True))
            .replace("{airflow_dags_location}", airflow_dags_location)
            .replace("{airflow_dags_env}", self.env)
            .replace("{airflowdocker_tag}", airflowdocker_tag)
        )
        with open("tmp-docker-compose.yml", "wb") as f:
            f.write(result.encode("utf-8"))

    def ensure_docker_compose_file(self):
        self.create_docker_compose()

        project = project_from_options(".", {"--file": ["tmp-docker-compose.yml"]})
        self.docker_compose_client = TopLevelCommand(project, {})
        self.has_created_docker_compose = True

    def __getattr__(self, attr):
        if not self.has_created_docker_compose:
            self.ensure_docker_compose_file()
        return getattr(self.docker_compose_client, attr)


def run():
    load_dotenv()

    docker_client = docker.from_env()
    cli = create_cli(docker_client)

    try:
        cli()
    except UserError as e:
        print(str(e))
        sys.exit(1)
