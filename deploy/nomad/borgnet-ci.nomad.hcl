# BorgNet CI on Nomad: a parameterized batch job that runs the test image once
# per Python version, one task group each.
#
# Register it once, then dispatch one run per commit:
#
#   nomad job run -var image=registry.service.consul:5000/borgnet-tests \
#     deploy/nomad/borgnet-ci.nomad.hcl
#   nomad job dispatch -meta image_tag=abc1234 borgnet-ci
#
# Each group runs <image>:<image_tag>-py<version>. scripts/ci.sh nomad builds
# and pushes those images, registers and dispatches this job, waits for every
# group, prints the logs, and exits non-zero if any version failed.

variable "image" {
  description = "Test image repository without a tag, e.g. registry.service.consul:5000/borgnet-tests."
  type        = string
  default     = "borgnet-tests"
}

variable "python_versions" {
  description = "Python versions to test. One task group runs per version."
  type        = list(string)
  default     = ["3.10", "3.11", "3.12", "3.13"]
}

variable "datacenters" {
  description = "Datacenters the CI runs may be placed in."
  type        = list(string)
  default     = ["*"]
}

variable "driver" {
  description = "Task driver that runs OCI images: docker or podman."
  type        = string
  default     = "docker"
}

variable "bus_url" {
  description = "IAC Bus URL for the live tests. Empty skips them."
  type        = string
  default     = ""
}

variable "bus_api_token" {
  description = "Bearer token for the IAC Bus. It is visible in the job spec, so use a dev token only."
  type        = string
  default     = ""
}

job "borgnet-ci" {
  type        = "batch"
  datacenters = var.datacenters

  parameterized {
    meta_required = ["image_tag"]
  }

  dynamic "group" {
    for_each = var.python_versions
    labels   = ["py${replace(group.value, ".", "")}"]

    content {
      # A failing test run is a result, not a fault, so never retry it.
      restart {
        attempts = 0
        mode     = "fail"
      }

      reschedule {
        attempts  = 0
        unlimited = false
      }

      task "pytest" {
        driver = var.driver

        config {
          # NOMAD_META_image_tag is filled in at dispatch time.
          image = "${var.image}:${NOMAD_META_image_tag}-py${group.value}"
        }

        env {
          BUS_URL       = var.bus_url
          BUS_API_TOKEN = var.bus_api_token
        }

        resources {
          cpu    = 500
          memory = 512
        }
      }
    }
  }
}
