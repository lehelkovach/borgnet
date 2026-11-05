#!/usr/bin/env bash
# BorgNet CI: run the test suite in OCI containers, one per Python version.
# npm runs this script: `npm test` is `scripts/ci.sh local`.
#
# Usage:
#   scripts/ci.sh local   Build one test image per Python version and run each here.
#   scripts/ci.sh build   Build the images, and push them if REGISTRY is set.
#
# Exits 0 only if every Python version passed.
#
# Environment:
#   PYTHON_VERSIONS    Versions to test. Default: "3.10 3.11 3.12 3.13".
#   CONTAINER_ENGINE   docker or podman. Default: podman if installed, else docker.
#   IMAGE_NAME         Image repository name. Default: borgnet-tests.
#   REGISTRY           Registry to push the built images to. Optional.
#   IMAGE_TAG          Tag prefix. Default: short git commit, plus -dirty if the
#                      tree has uncommitted changes. Images are <tag>-py<version>.
#   BUS_URL            IAC Bus URL to enable the live tests. Optional.
#   BUS_API_TOKEN      Bearer token for that bus. Optional.
#   CONTAINER_NETWORK  Network for local runs, e.g. "host" to reach a local bus.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_VERSIONS=${PYTHON_VERSIONS:-"3.10 3.11 3.12 3.13"}
IMAGE_NAME=${IMAGE_NAME:-borgnet-tests}

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

case "${1:-}" in
  local)
    build_images
    run_local
    ;;
  build)
    build_images
    ;;
  *)
    sed -n '2,9p' "$0" >&2
    exit 2
    ;;
esac
