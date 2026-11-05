# Test image for BorgNet CI. Builds with Docker, Podman, or Buildah and runs
# the pytest suite as its default command.
#
#   docker build -f Containerfile --build-arg PYTHON_VERSION=3.12 -t borgnet-tests:py3.12 .
#   docker run --rm borgnet-tests:py3.12
#
# `npm test` runs scripts/ci.sh, which builds one image per supported Python
# version and runs the suite in each.

ARG PYTHON_VERSION=3.12
FROM docker.io/library/python:${PYTHON_VERSION}-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install pytest pytest-cov \
 && useradd --create-home --uid 10001 borg

WORKDIR /app
COPY pyproject.toml README.md ./
COPY borgnet ./borgnet
RUN pip install .
COPY tests ./tests
COPY scripts ./scripts
RUN chown -R borg /app

USER borg

# Live IAC Bus tests run only when BUS_URL points at a reachable bus.
ENTRYPOINT ["python", "-m", "pytest"]
CMD ["--cov=borgnet", "--cov-report=term-missing"]
