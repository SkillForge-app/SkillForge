# Names shared by bootstrap/ and envs/<environment>/, so both (and backend-config.sh) agree on them
# without passing anything around. Azure needs globally unique names for the state storage account,
# the registry and the key vault, so they end in a short hash of the subscription id: switching to
# another subscription (another student's account) gives new names with no other change.
# No resources here.

variable "subscription_id" {
  description = "The Azure subscription id the names belong to."
  type        = string
}

variable "environment" {
  description = "staging or production."
  type        = string

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

locals {
  # The first 8 hex characters of sha1(subscription id). backend-config.sh computes the same.
  suffix = substr(sha1(var.subscription_id), 0, 8)
  short  = { staging = "stg", production = "prd" }[var.environment]
}

output "suffix" {
  value = local.suffix
}

output "prefix" {
  description = "Prefix for resources whose names only need to be unique in their resource group."
  value       = "sf-${local.short}"
}

output "state_resource_group" {
  value = "rg-skillforge-tfstate"
}

output "state_storage_account" {
  description = "One per subscription, shared by every environment (3-24 lowercase letters and digits)."
  value       = "stsftfstate${local.suffix}"
}

output "state_container" {
  value = "tfstate"
}

output "resource_group" {
  value = "rg-skillforge-${var.environment}"
}

output "registry" {
  description = "Container registry name (5-50 letters and digits, globally unique)."
  value       = "acrskillforge${local.short}${local.suffix}"
}

output "key_vault" {
  description = "Key Vault name (3-24 characters, globally unique)."
  value       = "kv-sf-${local.short}-${local.suffix}"
}

output "postgres" {
  description = "Postgres flexible server name (globally unique DNS name)."
  value       = "psql-sf-${local.short}-${local.suffix}"
}
