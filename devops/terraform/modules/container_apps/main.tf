# The Container Apps environment (Consumption workload profile) and the stack that runs in it:
#   web     Next.js, external HTTP ingress, 0.25 vCPU / 0.5 GiB, scales to zero
#   api     FastAPI, external HTTP ingress, 0.5 vCPU / 1 GiB, scales to zero
#   worker  RQ + AI pipeline (the baked worker image), no ingress, 1 vCPU / 2 GiB, scales from zero
#           on the length of the RQ queue (KEDA `redis` scaler)
#   redis   the same pinned redis image as compose, internal TCP ingress, always 1 replica, no
#           persistence (queued jobs are lost on a restart: risk R5)
#   migrate a manual Container Apps job (the api image): `alembic upgrade head`, started by the deploy
# Every app has max 1 replica, which bounds the worst-case cost (devops/terraform/README.md).
#
# Images: the first apply that creates an app uses image_tag; after that the deploy workflow changes
# images (`az containerapp update --image`) and Terraform ignores them.
# Secrets: Key Vault references through one user-assigned identity; no secret value is stored here.

terraform {
  required_providers {
    azurerm = {
      source = "hashicorp/azurerm"
    }
    random = {
      source = "hashicorp/random"
    }
  }
}

variable "prefix" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "log_analytics_workspace_id" {
  type = string
}

variable "registry_id" {
  type = string
}

variable "registry_login_server" {
  type = string
}

variable "key_vault_id" {
  type = string
}

variable "key_vault_uri" {
  type = string
}

variable "database_url_secret_id" {
  description = "Versionless Key Vault id of DATABASE_URL (modules/postgres)."
  type        = string
}

variable "apps_enabled" {
  description = "false: only the environment, identity and secrets (first run, before any image exists)."
  type        = bool
}

variable "image_tag" {
  description = "Image tag for apps created by this apply (ignored for apps that already exist)."
  type        = string
}

variable "redis_image" {
  description = "Pinned by digest, the same as compose.yaml."
  type        = string
}

variable "redis_password_version" {
  description = "Bump to generate and send a new redis password."
  type        = number
  default     = 1
}

variable "worker_key_vault_secrets" {
  description = "Extra worker environment variables from Key Vault: {ENV_NAME = \"secret-name\"}. The secrets must exist first (people enter LLM provider keys by hand)."
  type        = map(string)
  default     = {}
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  names = {
    web     = "${var.prefix}-web"
    api     = "${var.prefix}-api"
    worker  = "${var.prefix}-worker"
    redis   = "${var.prefix}-redis"
    migrate = "${var.prefix}-migrate"
  }
  images = {
    web    = "${var.registry_login_server}/skillforge-web:${var.image_tag}"
    api    = "${var.registry_login_server}/skillforge-api:${var.image_tag}"
    worker = "${var.registry_login_server}/skillforge-worker:${var.image_tag}"
  }
  # RQ keeps a queue named `skills` in the Redis list `rq:queue:skills` (Backend's worker command:
  # rq worker ... skills). Confirm with Backend when the real worker lands.
  rq_queue_list = "rq:queue:skills"
  # Container Apps secret names: lowercase letters, digits and dashes.
  worker_extra = { for env_name, secret in var.worker_key_vault_secrets :
    env_name => {
      secret_name = lower(replace(env_name, "_", "-"))
      id          = "${var.key_vault_uri}secrets/${secret}"
    }
  }
  # redis-server reads the password from the environment (Key Vault), never from the command line.
  redis_command = "exec redis-server --save '' --appendonly no --requirepass \"$REDIS_PASSWORD\""
}

# ---------------------------------------------------------------- identity and access

resource "azurerm_user_assigned_identity" "apps" {
  name                = "id-${var.prefix}-apps"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = var.registry_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "key_vault_secrets_user" {
  scope                = var.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
  principal_type       = "ServicePrincipal"
}

# ---------------------------------------------------------------- redis password

ephemeral "random_password" "redis" {
  length  = 40
  special = false
}

resource "azurerm_key_vault_secret" "redis_password" {
  name             = "redis-password"
  key_vault_id     = var.key_vault_id
  value_wo         = ephemeral.random_password.redis.result
  value_wo_version = var.redis_password_version
}

resource "azurerm_key_vault_secret" "redis_url" {
  name             = "redis-url"
  key_vault_id     = var.key_vault_id
  value_wo         = "redis://:${ephemeral.random_password.redis.result}@${local.names.redis}:6379/0"
  value_wo_version = var.redis_password_version
}

# ---------------------------------------------------------------- environment

resource "azurerm_container_app_environment" "this" {
  name                       = "cae-${var.prefix}"
  resource_group_name        = var.resource_group_name
  location                   = var.location
  log_analytics_workspace_id = var.log_analytics_workspace_id
  logs_destination           = "log-analytics"
  tags                       = var.tags

  # Consumption only: no Dedicated profile, so no plan management charge.
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}

# ---------------------------------------------------------------- redis

resource "azurerm_container_app" "redis" {
  count = var.apps_enabled ? 1 : 0

  name                         = local.names.redis
  resource_group_name          = var.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.this.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  secret {
    name                = "redis-password"
    identity            = azurerm_user_assigned_identity.apps.id
    key_vault_secret_id = azurerm_key_vault_secret.redis_password.versionless_id
  }

  # Internal TCP: reachable only from apps in this environment, as `<name>:6379`. (External TCP
  # would need a VNet; internal does not.)
  ingress {
    external_enabled = false
    transport        = "tcp"
    target_port      = 6379
    exposed_port     = 6379

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name    = "redis"
      image   = var.redis_image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["sh", "-c", local.redis_command]

      env {
        name        = "REDIS_PASSWORD"
        secret_name = "redis-password"
      }
    }
  }

  depends_on = [azurerm_role_assignment.key_vault_secrets_user]
}

# ---------------------------------------------------------------- api

resource "azurerm_container_app" "api" {
  count = var.apps_enabled ? 1 : 0

  name                         = local.names.api
  resource_group_name          = var.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.this.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  registry {
    server   = var.registry_login_server
    identity = azurerm_user_assigned_identity.apps.id
  }

  secret {
    name                = "database-url"
    identity            = azurerm_user_assigned_identity.apps.id
    key_vault_secret_id = var.database_url_secret_id
  }

  secret {
    name                = "redis-url"
    identity            = azurerm_user_assigned_identity.apps.id
    key_vault_secret_id = azurerm_key_vault_secret.redis_url.versionless_id
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 1

    container {
      name   = "api"
      image  = local.images.api
      cpu    = 0.5
      memory = "1Gi"

      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }

      env {
        name        = "REDIS_URL"
        secret_name = "redis-url"
      }
    }

    http_scale_rule {
      name                = "http"
      concurrent_requests = "10"
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }

  depends_on = [azurerm_role_assignment.acr_pull, azurerm_role_assignment.key_vault_secrets_user]
}

# ---------------------------------------------------------------- web

resource "azurerm_container_app" "web" {
  count = var.apps_enabled ? 1 : 0

  name                         = local.names.web
  resource_group_name          = var.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.this.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  registry {
    server   = var.registry_login_server
    identity = azurerm_user_assigned_identity.apps.id
  }

  ingress {
    external_enabled = true
    target_port      = 3000
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 1

    # NEXT_PUBLIC_API_BASE_URL is baked into the image at build time (output api_url).
    container {
      name   = "web"
      image  = local.images.web
      cpu    = 0.25
      memory = "0.5Gi"
    }

    http_scale_rule {
      name                = "http"
      concurrent_requests = "10"
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }

  depends_on = [azurerm_role_assignment.acr_pull]
}

# ---------------------------------------------------------------- worker

resource "azurerm_container_app" "worker" {
  count = var.apps_enabled ? 1 : 0

  name                         = local.names.worker
  resource_group_name          = var.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.this.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  registry {
    server   = var.registry_login_server
    identity = azurerm_user_assigned_identity.apps.id
  }

  secret {
    name                = "database-url"
    identity            = azurerm_user_assigned_identity.apps.id
    key_vault_secret_id = var.database_url_secret_id
  }

  secret {
    name                = "redis-url"
    identity            = azurerm_user_assigned_identity.apps.id
    key_vault_secret_id = azurerm_key_vault_secret.redis_url.versionless_id
  }

  secret {
    name                = "redis-password"
    identity            = azurerm_user_assigned_identity.apps.id
    key_vault_secret_id = azurerm_key_vault_secret.redis_password.versionless_id
  }

  dynamic "secret" {
    for_each = local.worker_extra
    content {
      name                = secret.value.secret_name
      identity            = azurerm_user_assigned_identity.apps.id
      key_vault_secret_id = secret.value.id
    }
  }

  # No ingress: the KEDA rule below is what starts it (without a rule it would never start).
  template {
    min_replicas = 0
    max_replicas = 1

    container {
      name   = "worker"
      image  = local.images.worker
      cpu    = 1
      memory = "2Gi"

      # The model is baked into the image (target `baked`): never download at runtime.
      env {
        name  = "HF_HUB_OFFLINE"
        value = "1"
      }

      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }

      env {
        name        = "REDIS_URL"
        secret_name = "redis-url"
      }

      dynamic "env" {
        for_each = local.worker_extra
        content {
          name        = env.key
          secret_name = env.value.secret_name
        }
      }
    }

    custom_scale_rule {
      name             = "rq-queue"
      custom_rule_type = "redis"
      metadata = {
        address    = "${local.names.redis}:6379"
        listName   = local.rq_queue_list
        listLength = "5"
      }

      authentication {
        secret_name       = "redis-password"
        trigger_parameter = "password"
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }

  depends_on = [azurerm_role_assignment.acr_pull, azurerm_role_assignment.key_vault_secrets_user]
}

# ---------------------------------------------------------------- migrate job

resource "azurerm_container_app_job" "migrate" {
  count = var.apps_enabled ? 1 : 0

  name                         = local.names.migrate
  resource_group_name          = var.resource_group_name
  location                     = var.location
  container_app_environment_id = azurerm_container_app_environment.this.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 600
  replica_retry_limit          = 0
  tags                         = var.tags

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  registry {
    server   = var.registry_login_server
    identity = azurerm_user_assigned_identity.apps.id
  }

  secret {
    name                = "database-url"
    identity            = azurerm_user_assigned_identity.apps.id
    key_vault_secret_id = var.database_url_secret_id
  }

  template {
    container {
      name    = "migrate"
      image   = local.images.api
      cpu     = 0.5
      memory  = "1Gi"
      command = ["alembic", "-c", "backend/alembic.ini", "upgrade", "head"]

      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }

  depends_on = [azurerm_role_assignment.acr_pull, azurerm_role_assignment.key_vault_secrets_user]
}

# ---------------------------------------------------------------- outputs

output "environment_id" {
  value = azurerm_container_app_environment.this.id
}

output "default_domain" {
  value = azurerm_container_app_environment.this.default_domain
}

output "api_url" {
  description = "Known as soon as the environment exists (the web build needs it before the apps do)."
  value       = "https://${local.names.api}.${azurerm_container_app_environment.this.default_domain}"
}

output "web_url" {
  value = "https://${local.names.web}.${azurerm_container_app_environment.this.default_domain}"
}

output "names" {
  value = local.names
}

output "app_ids" {
  description = "Container app ids by role (empty while apps_enabled is false)."
  value = var.apps_enabled ? {
    web    = azurerm_container_app.web[0].id
    api    = azurerm_container_app.api[0].id
    worker = azurerm_container_app.worker[0].id
    redis  = azurerm_container_app.redis[0].id
  } : {}
}

output "apps_identity_principal_id" {
  value = azurerm_user_assigned_identity.apps.principal_id
}
