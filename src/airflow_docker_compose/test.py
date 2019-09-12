import os

from compose.utils import split_buffer


def test_dag(docker_client, dag_dir=".", tag="latest", extra_test_dir="tests"):
    dag_dir = os.path.abspath(dag_dir)
    extra_test_dir = os.path.abspath(extra_test_dir)

    volumes = ["{dag_dir}:/airflow/dags".format(dag_dir=dag_dir)]
    if os.path.exists(extra_test_dir):
        volumes.append("{extra_test_dir}:/airflow/tests/ext".format(extra_test_dir=extra_test_dir))

    result = docker_client.containers.run(
        "airflowdocker/tester:{tag}".format(tag=tag),
        detach=True,
        tty=True,
        stdout=False,
        stderr=True,
        volumes=volumes,
    )
    try:
        logs = result.logs(stream=True, follow=True)
        for line in split_buffer(logs):
            print(line, end="")
    finally:
        result.wait()
        result.remove()
