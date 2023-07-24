# airflow-docker-compose
[![CircleCI](https://circleci.com/gh/airflowdocker/airflow-docker-compose.svg?style=svg)](https://circleci.com/gh/airflowdocker/airflow-docker-compose) [![codecov](https://codecov.io/gh/airflowdocker/airflow-docker-compose/branch/master/graph/badge.svg)](https://codecov.io/gh/airflowdocker/airflow-docker-compose)

## Description
A reasonably light wrapper around `docker-compose` to make it simple to start a local
airflow instance in docker.

## Usage

```bash
airflow-docker-compose --help
airflow-docker-compose up
```


## Configuration

Note, this library assumes the `docker-compose` utility is available in your path.

In order to use this tool, you should have a local `dags` folder containing your dags.
You should also have a `pyproject.toml` file which minimally looks like

```ini
[tool.airflow-docker-compose]
docker-network = 'network-name'
```

In order to set airflow configuration, you can use the `airflow-environment-variables` key.
This allows you to set any `airflow.cfg` variables like so:

```ini
[tool.airflow-docker-compose]
airflow-environment-variables = {
    AIRWFLOW_WORKER_COUNT = 4
    AIRFLOW__AIRFLOWDOCKER__FORCE_PULL = 'false'
}
