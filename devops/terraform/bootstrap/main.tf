# One-time setup, run by a person with Owner on the subscription (az login), BEFORE any workflow
# can deploy. It creates what CI needs to exist first:
#   - rg-skillforge-tfstate: the state storage account (AAD only, versioning, soft delete) and the
#     GitHub deploy identity (user-assigned managed identity, OIDC federated credential: no keys);
#   - rg-skillforge-<environment>: the empty resource group envs/<environment>/ fills;
#   - the container registry (modules/registry), because images are pushed before the first apply
#     that creates the container apps;
#   - the deploy identity's role assignments, all scoped to those resource groups.
# Its own state is local (terraform.tfstate here, git-ignored). It holds ids, no secrets. Keep it
# until staging is gone, or re-import (devops/terraform/README.md).

terraform {
  required_version = "= 1.17.1"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 5.12.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id
  tenant_id                       = var.tenant_id
  resource_provider_registrations = "none"
  storage_use_azuread             = true
}

variable "subscription_id" {
  description = "The Azure subscription (whose Azure for Students account hosts staging). No default."
  type        = string
}

variable "tenant_id" {
  description = "The Microsoft Entra tenant of that subscription. No default."
  type        = string
}

variable "location" {
  description = "An Azure region the subscription's \"Allowed locations\" policy permits. No default."
  type        = string
}

variable "environment" {
  type    = string
  default = "staging"
}

variable "github_repository" {
  description = "owner/name of the repository whose workflows may deploy."
  type        = string
  default     = "SkillForge-app/SkillForge"
}

variable "github_environment" {
  description = "Only jobs that run in this GitHub environment get an Azure token."
  type        = string
  default     = "staging"
}

module "naming" {
  source          = "../modules/naming"
  subscription_id = var.subscription_id
  environment     = var.environment
}

data "azurerm_client_config" "current" {}

locals {
  tags = {
    project    = "skillforge"
    managed-by = "terraform-bootstrap"
  }
  # Roles the deploy identity may grant (to the apps' identity) and nothing else.
  delegable_roles = {
    acr_pull                      = "7f951dda-4ed3-4680-a7ca-43fe172d538d" # AcrPull
    key_vault_secrets_user        = "4633458b-17de-408a-b874-0445c86b69e6" # Key Vault Secrets User
    storage_blob_data_contributor = "ba92f5b4-2d11-453d-a403-e96b0029c9fe" # Storage Blob Data Contributor
  }
  delegable_list = join(", ", values(local.delegable_roles))
}

# ---------------------------------------------------------------- state

resource "azurerm_resource_group" "tfstate" {
  name     = module.naming.state_resource_group
  location = var.location
  tags     = local.tags
}

resource "azurerm_storage_account" "tfstate" {
  name                            = module.naming.state_storage_account
  resource_group_name             = azurerm_resource_group.tfstate.name
  location                        = var.location
  account_kind                    = "StorageV2"
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  access_tier                     = "Hot"
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  allow_nested_items_to_be_public = false
  tags                            = local.tags

  blob_properties {
    versioning_enabled = true

    delete_retention_policy {
      days = 14
    }

    container_delete_retention_policy {
      days = 14
    }
  }
}

resource "azurerm_storage_container" "tfstate" {
  name                  = module.naming.state_container
  storage_account_id    = azurerm_storage_account.tfstate.id
  container_access_type = "private"
}

# ---------------------------------------------------------------- environment resource group

resource "azurerm_resource_group" "env" {
  name     = module.naming.resource_group
  location = var.location
  tags     = merge(local.tags, { environment = var.environment })
}

module "registry" {
  source              = "../modules/registry"
  name                = module.naming.registry
  resource_group_name = azurerm_resource_group.env.name
  location            = var.location
  tags                = merge(local.tags, { environment = var.environment })
}

# ---------------------------------------------------------------- GitHub deploy identity (OIDC)

resource "azurerm_user_assigned_identity" "deploy" {
  name                = "id-skillforge-${var.environment}-deploy"
  resource_group_name = azurerm_resource_group.tfstate.name
  location            = var.location
  tags                = local.tags
}

resource "azurerm_federated_identity_credential" "github" {
  name                      = "github-${var.github_environment}"
  user_assigned_identity_id = azurerm_user_assigned_identity.deploy.id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = "https://token.actions.githubusercontent.com"
  subject                   = "repo:${var.github_repository}:environment:${var.github_environment}"
}

# Read and write the state (data plane; shared keys are off).
resource "azurerm_role_assignment" "deploy_state" {
  scope                = azurerm_storage_account.tfstate.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
  principal_type       = "ServicePrincipal"
}

# Create and change everything in the environment's resource group.
resource "azurerm_role_assignment" "deploy_contributor" {
  scope                = azurerm_resource_group.env.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
  principal_type       = "ServicePrincipal"
}

# Write the generated secrets (Postgres, redis) into the environment's Key Vault.
resource "azurerm_role_assignment" "deploy_secrets_officer" {
  scope                = azurerm_resource_group.env.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
  principal_type       = "ServicePrincipal"
}

# Push images.
resource "azurerm_role_assignment" "deploy_acr_push" {
  scope                = module.registry.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
  principal_type       = "ServicePrincipal"
}

# Grant roles to the apps' identity, but ONLY the three roles in local.delegable_roles (an ABAC
# condition on Role Based Access Control Administrator), so the deploy identity cannot make itself
# or anything else Owner.
resource "azurerm_role_assignment" "deploy_rbac_admin" {
  scope                = azurerm_resource_group.env.id
  role_definition_name = "Role Based Access Control Administrator"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
  principal_type       = "ServicePrincipal"
  condition_version    = "2.0"
  condition            = <<-EOT
    (
     (
      !(ActionMatches{'Microsoft.Authorization/roleAssignments/write'})
     )
     OR
     (
      @Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${local.delegable_list}}
     )
    )
    AND
    (
     (
      !(ActionMatches{'Microsoft.Authorization/roleAssignments/delete'})
     )
     OR
     (
      @Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${local.delegable_list}}
     )
    )
  EOT
}

# The person running bootstrap may enter secrets by hand (LLM provider keys): Owner alone does not
# give Key Vault data access in RBAC mode.
resource "azurerm_role_assignment" "operator_secrets_officer" {
  scope                = azurerm_resource_group.env.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

# ---------------------------------------------------------------- outputs

output "github_environment_secrets" {
  description = "Set these as secrets of the GitHub environment named in github_environment."
  value = {
    AZURE_CLIENT_ID       = azurerm_user_assigned_identity.deploy.client_id
    AZURE_TENANT_ID       = var.tenant_id
    AZURE_SUBSCRIPTION_ID = var.subscription_id
  }
}

output "state" {
  description = "Where envs/<environment>/ keeps its state (backend-config.sh derives the same names)."
  value = {
    resource_group_name  = azurerm_resource_group.tfstate.name
    storage_account_name = azurerm_storage_account.tfstate.name
    container_name       = azurerm_storage_container.tfstate.name
  }
}

output "registry_login_server" {
  value = module.registry.login_server
}

output "resource_group" {
  value = azurerm_resource_group.env.name
}
