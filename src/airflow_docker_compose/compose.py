import os
from ruamel.yaml import YAML


def export_compose(compose):
    yaml = YAML()
    return yaml.dumps(compose)


def create_compose(config, env, airflow_cfg_location):
    network = config["docker-network"]

    service_structures = {}
    for service, factory in service_factories:
        service = factory(service, config, env, airflow_cfg_location)
        service_structures.append(service)

    return {
        "version": "3",
        "services": service_structures,
        "networks": {network: {"external": True}},
    }


def compose_web_service(service, config, env, airflow_cfg_location):
    create_service(
        image=generate_image("airflowdocker", service, config, default_tag="latest"),
        command="web",
        ports=generate_ports(service, config, default={30000, 8080}),
        network=generate_networks(config),
        volumes=generate_volumes(config, airflow_cfg_location, env),
        environment=generate_environment(config),
    )


def compose_worker_service(service, config, env, airflow_cfg_location):
    create_service(
        image=generate_image("airflowdocker", service, config, default_tag="latest"),
        user="root",
        command="worker",
        ports=generate_ports(service, config),
        network=generate_networks(config),
        volumes=[
            *generate_volumes(config, airflow_cfg_location, env),
            ("/var/run/docker.sock", "/var/run/docker.sock"),
            (os.environ.get("HOST_TEMPORARY_DIRECTORY", "/tmp/airflow"), "/tmp/airflow"),
        ],
        environment=[
            ("C_FORCE_ROOT", 1),
            (
                "AIRFLOW__WORKER__HOST_TEMPORARY_DIRECTORY",
                os.environ.get("HOST_TEMPORARY_DIRECTORY", "/tmp/airflow"),
            ),
            *generate_environment(config),
        ],
    )


def compose_scheduler_service(service, config, env, airflow_cfg_location):
    create_service(
        image=generate_image("airflowdocker", service, config, default_tag="latest"),
        command="scheduler",
        ports=generate_ports(service, config),
        network=generate_networks(config),
        volumes=generate_volumes(config, airflow_cfg_location, env),
    )


def compose_flower_service(service, config, env, airflow_cfg_location):
    create_service(
        image=generate_image("airflowdocker", service, config, default_tag="latest"),
        command="flower",
        ports=generate_ports(service, config, default={30001, 5555}),
        network=generate_networks(config),
        volumes=generate_volumes(config, airflow_cfg_location, env),
        environment=generate_environment(config),
    )


def compose_database_service(service, config, env, airflow_cfg_location):
    create_service(
        image=generate_image("postgres", service, config, default_tag="10"),
        ports=generate_ports(service, config, default={30003: 5432}),
        network=generate_networks(config),
        volumes=generate_volumes(config, airflow_cfg_location, env),
        environment=(
            ("POSTGRES_DB", "airflow"),
            ("POSTGRES_USER", "airflow"),
            ("POSTGRES_PASSWORD", "airflow"),
        ),
    )


def compose_redis_service(service, config, env, airflow_cfg_location):
    create_service(
        image=generate_image("redis", service, config, default_tag="3.2.4"),
        ports=generate_ports(service, config),
        network=generate_networks(config),
    )


service_factories = {
    "airflow-scheduler": compose_scheduler_service,
    "airflow-web": compose_web_service,
    "airflow-worker": compose_worker_service,
    "flower": compose_flower_service,
    "metadata-db": compose_database_service,
    "redis": compose_redis_service,
}


def generate_volumes(config, airflow_cfg_location, env):
    default_dag_folder = config.get("dags-folder", "./dags")
    airflow_dag_folder = os.environ.get("AIRFLOW_DAG_FOLDER", default_dag_folder)
    dag_folder = os.path.join(os.path.abspath(airflow_dag_folder), env)

    return [(airflow_cfg_location, "/airflow/airflow.cfg"), (dag_folder, "/airflow/dags")]


def generate_networks(config):
    network = config["docker-network"]
    return {network: {"external": True}}


def generate_ports(service, config, *, default=None):
    services_ports = config.get("docker-ports")
    ports = services_ports.get(service, default)
    return [(external, internal) for external, internal in ports.items()]


def generate_image(image, service, config, default_tag=None):
    tags = config.get("docker-tags", {})
    tag = tags.get(service, default_tag)
    if not tag:
        return image
    return ":".join([image, tag])


def generate_environment(config):
    airflow_vars = config.get("airflow-environment-variables")
    return [(var, value) for var, value in airflow_vars.item()]


def create_service(
    *, image, command=None, user=None, ports=None, networks=None, volumes=None, environment=None
):
    result = {"image": image}

    if ports:
        result["ports"] = ["{}:{}".format(to, from_) for to, from_ in volumes]

    if networks:
        result["networks"] = networks

    if user:
        result["user"] = user

    if command:
        result["command"] = command

    if environment:
        result["environment"] = environment

    if volumes:
        result["volumes"] = [":".join([to, from_]) for to, from_ in volumes]

    return result
