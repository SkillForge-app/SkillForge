# Account-specific values have NO default: switching to another student's subscription changes
# staging.tfvars (location) and the GitHub environment secrets (subscription and tenant ids, which CI
# passes as TF_VAR_subscription_id / TF_VAR_tenant_id), nothing else.

variable "subscription_id" {
  description = "The Azure subscription hosting staging. In CI: TF_VAR_subscription_id from the AZURE_SUBSCRIPTION_ID secret."
  type        = string
}

variable "tenant_id" {
  description = "The subscription's Microsoft Entra tenant. In CI: TF_VAR_tenant_id from the AZURE_TENANT_ID secret."
  type        = string
}

variable "location" {
  description = "A region the subscription's \"Allowed locations\" policy permits, with Postgres flexible B1ms and PG 18. Must match bootstrap's."
  type        = string
}

variable "apps_enabled" {
  description = "false on the first run (no image exists yet): only the environment, database, vault and logs. Then true."
  type        = bool
  default     = false
}

variable "image_tag" {
  description = "Tag of the images to create new apps with (the deploy passes the git sha). Ignored for apps that already exist."
  type        = string
  default     = "unset"

  validation {
    condition     = !var.apps_enabled || var.image_tag != "unset"
    error_message = "apps_enabled = true needs image_tag (the deploy workflow passes the git sha)."
  }
}

variable "redis_image" {
  description = "The same pinned image as compose.yaml's redis service."
  type        = string
  default     = "docker.io/library/redis:8.8.2-alpine@sha256:f4ded511357f7c60551133fbceb0d07874a2240bfe3d1baaa49769a70ff83465"
}

variable "enable_app_blob" {
  description = "Create the app blob storage account and container (nothing needs it yet)."
  type        = bool
  default     = false
}

variable "alert_emails" {
  description = "Who gets the cost-guard (and, if enabled, budget) emails."
  type        = list(string)
  default     = []
}

variable "enable_budget" {
  description = "Only if the portal shows Cost Management budgets working for this offer (README, manual step 4)."
  type        = bool
  default     = false
}

variable "worker_key_vault_secrets" {
  description = "Extra worker env vars from Key Vault, {ENV_NAME = \"secret-name\"}, added once the secrets exist (LLM provider keys)."
  type        = map(string)
  default     = {}
}

variable "postgres_password_version" {
  description = "Bump to rotate the Postgres admin password."
  type        = number
  default     = 1
}

variable "redis_password_version" {
  description = "Bump to rotate the redis password."
  type        = number
  default     = 1
}
