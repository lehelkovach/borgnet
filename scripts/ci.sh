#!/usr/bin/env bash
# BorgNet CI: run the test suite in OCI containers, locally or on Nomad.
#
# Usage:
#   scripts/ci.sh local   Build one test image per Python version and run each here.
#   scripts/ci.sh build   Build the images, and push them if REGISTRY is set.
#   scripts/ci.sh nomad   Build (and push) the images, dispatch the Nomad CI job,
#                         wait for every Python version, and print the logs.
#
# Exits 0 only if every Python version passed.
#
# Environment:
#   PYTHON_VERSIONS    Versions to test. Default: "3.10 3.11 3.12 3.13".
#   CONTAINER_ENGINE   docker or podman. Default: podman if installed, else docker.
#   IMAGE_NAME         Image repository name. Default: borgnet-tests.
#   REGISTRY           Registry to push to, e.g. registry.service.consul:5000.
#                      Leave unset when the Nomad clients use this machine's engine.
#   IMAGE_TAG          Tag prefix. Default: short git commit, plus -dirty if the
#                      tree has uncommitted changes. Images are <tag>-py<version>.
#   BUS_URL            IAC Bus URL to enable the live tests. Optional.
#   BUS_API_TOKEN      Bearer token for that bus. Optional.
#   CONTAINER_NETWORK  Network for local runs, e.g. "host" to reach a local bus.
#   NOMAD_JOB_FILE     Default: deploy/nomad/borgnet-ci.nomad.hcl.
#   NOMAD_DRIVER       Nomad task driver, docker or podman. Default: docker.
#   NOMAD_TIMEOUT      Seconds to wait for a Nomad run. Default: 900.
#   NOMAD_ADDR, NOMAD_TOKEN, NOMAD_CACERT and friends are read by the nomad CLI.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_VERSIONS=${PYTHON_VERSIONS:-"3.10 3.11 3.12 3.13"}
IMAGE_NAME=${IMAGE_NAME:-borgnet-tests}
NOMAD_JOB_FILE=${NOMAD_JOB_FILE:-deploy/nomad/borgnet-ci.nomad.hcl}
NOMAD_JOB_NAME=borgnet-ci
NOMAD_DRIVER=${NOMAD_DRIVER:-docker}
NOMAD_TIMEOUT=${NOMAD_TIMEOUT:-900}

if [[ -z "${CONTAINER_ENGINE:-}" ]]; then
  if command -v podman >/dev/null 2>&1; then
    CONTAINER_ENGINE=podman
  elif command -v docker >/dev/null 2>&1; then
    CONTAINER_ENGINE=docker
  else
    echo "error: neither podman nor docker is installed" >&2
    exit 2
  fi
fi

if [[ -z "${IMAGE_TAG:-}" ]]; then
  IMAGE_TAG=$(git rev-parse --short HEAD 2>/dev/null || echo local)
  if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
    IMAGE_TAG="${IMAGE_TAG}-dirty"
  fi
fi

if [[ -n "${REGISTRY:-}" ]]; then
  IMAGE_REPO="${REGISTRY}/${IMAGE_NAME}"
else
  IMAGE_REPO="${IMAGE_NAME}"
fi

RESULTS=()
FAILED=0

image_ref() {
  echo "${IMAGE_REPO}:${IMAGE_TAG}-py$1"
}

build_images() {
  local v ref
  for v in $PYTHON_VERSIONS; do
    ref=$(image_ref "$v")
    echo "==> Building ${ref}"
    "$CONTAINER_ENGINE" build -f Containerfile --build-arg "PYTHON_VERSION=${v}" -t "$ref" .
    if [[ -n "${REGISTRY:-}" ]]; then
      echo "==> Pushing ${ref}"
      "$CONTAINER_ENGINE" push "$ref"
    fi
  done
}

record() {
  RESULTS+=("$(printf '%-10s %s' "$1" "$2")")
  if [[ "$2" != "passed" ]]; then
    FAILED=1
  fi
}

summary() {
  echo
  echo "==> Summary for ${IMAGE_TAG}"
  printf '%s\n' "${RESULTS[@]}"
  if [[ "$FAILED" -ne 0 ]]; then
    echo "FAILED"
    exit 1
  fi
  echo "PASSED"
}

run_local() {
  local v ref
  local -a args
  for v in $PYTHON_VERSIONS; do
    ref=$(image_ref "$v")
    args=(run --rm)
    if [[ -n "${CONTAINER_NETWORK:-}" ]]; then
      args+=(--network "$CONTAINER_NETWORK")
    fi
    if [[ -n "${BUS_URL:-}" ]]; then
      args+=(-e "BUS_URL=${BUS_URL}")
    fi
    if [[ -n "${BUS_API_TOKEN:-}" ]]; then
      args+=(-e "BUS_API_TOKEN=${BUS_API_TOKEN}")
    fi
    echo "==> Testing on Python ${v}"
    if "$CONTAINER_ENGINE" "${args[@]}" "$ref"; then
      record "py${v}" passed
    else
      record "py${v}" failed
    fi
  done
  summary
}

run_nomad() {
  if ! command -v nomad >/dev/null 2>&1; then
    echo "error: the nomad CLI is not installed" >&2
    exit 2
  fi

  local versions_hcl v
  versions_hcl=""
  for v in $PYTHON_VERSIONS; do
    versions_hcl="${versions_hcl}\"${v}\","
  done
  versions_hcl="[${versions_hcl%,}]"

  local -a vars=(
    -var "image=${IMAGE_REPO}"
    -var "python_versions=${versions_hcl}"
    -var "driver=${NOMAD_DRIVER}"
  )
  if [[ -n "${BUS_URL:-}" ]]; then
    vars+=(-var "bus_url=${BUS_URL}")
  fi
  if [[ -n "${BUS_API_TOKEN:-}" ]]; then
    vars+=(-var "bus_api_token=${BUS_API_TOKEN}")
  fi

  echo "==> Registering ${NOMAD_JOB_NAME} from ${NOMAD_JOB_FILE}"
  nomad job run "${vars[@]}" "$NOMAD_JOB_FILE"

  echo "==> Dispatching ${NOMAD_JOB_NAME} for ${IMAGE_TAG}"
  local out child
  out=$(nomad job dispatch -detach -meta "image_tag=${IMAGE_TAG}" "$NOMAD_JOB_NAME")
  echo "$out"
  child=$(awk -F'= ' '/Dispatched Job ID/ {print $2}' <<<"$out" | tr -d '[:space:]')
  if [[ -z "$child" ]]; then
    echo "error: could not read the dispatched job ID" >&2
    exit 1
  fi

  local expected allocs finished deadline
  expected=$(wc -w <<<"$PYTHON_VERSIONS")
  deadline=$((SECONDS + NOMAD_TIMEOUT))
  echo "==> Waiting for ${expected} task group(s) in ${child}"
  while true; do
    allocs=$(nomad job allocs -t '{{range .}}{{.ID}} {{.TaskGroup}} {{.ClientStatus}}{{"\n"}}{{end}}' "$child" 2>/dev/null || true)
    finished=$(awk '$3 == "complete" || $3 == "failed" || $3 == "lost"' <<<"$allocs" | wc -l)
    if [[ "$finished" -ge "$expected" ]]; then
      break
    fi
    if [[ "$SECONDS" -ge "$deadline" ]]; then
      echo "error: timed out after ${NOMAD_TIMEOUT}s" >&2
      nomad job status "$child" >&2 || true
      exit 1
    fi
    sleep 5
  done

  local id group status
  while read -r id group status; do
    if [[ -z "$id" ]]; then
      continue
    fi
    echo
    echo "==> ${group}: ${status} (allocation ${id})"
    nomad alloc logs "$id" pytest || true
    if [[ "$status" != "complete" ]]; then
      nomad alloc logs -stderr "$id" pytest || true
      nomad alloc status "$id" | sed -n '/Recent Events/,$p' || true
      record "$group" failed
    else
      record "$group" passed
    fi
  done < <(sort -k2 <<<"$allocs")

  summary
}

case "${1:-}" in
  local)
    build_images
    run_local
    ;;
  build)
    build_images
    ;;
  nomad)
    build_images
    run_nomad
    ;;
  *)
    sed -n '2,9p' "$0" >&2
    exit 2
    ;;
esac
