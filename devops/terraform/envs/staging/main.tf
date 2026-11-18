# Staging (OPS-04): Azure for Students, about $27-49/month (devops/terraform/README.md, "Budget").
# The resource group and the registry come from bootstrap/; everything else is here.

module "naming" {
  source          = "../../modules/naming"
  subscription_id = var.subscription_id
  environment     = "staging"
}

locals {
  tags = {
    project     = "skillforge"
    environment = "staging"
    managed-by  = "terraform"
  }
}

data "azurerm_resource_group" "this" {
  name = module.naming.resource_group
}

data "azurerm_container_registry" "this" {
  name                = module.naming.registry
  resource_group_name = data.azurerm_resource_group.this.name
}

module "observability" {
  source              = "../../modules/observability"
  prefix              = module.naming.prefix
  resource_group_name = data.azurerm_resource_group.this.name
  location            = var.location
  subscription_id     = var.subscription_id
  alert_emails        = var.alert_emails
  enable_budget       = var.enable_budget
  tags                = local.tags
}

module "keyvault" {
  source              = "../../modules/keyvault"
  name                = module.naming.key_vault
  resource_group_name = data.azurerm_resource_group.this.name
  location            = var.location
  tenant_id           = var.tenant_id
  tags                = local.tags
}

module "postgres" {
  source              = "../../modules/postgres"
  name                = module.naming.postgres
  resource_group_name = data.azurerm_resource_group.this.name
  location            = var.location
  key_vault_id        = module.keyvault.id
  password_version    = var.postgres_password_version
  tags                = local.tags
}

module "container_apps" {
  source                     = "../../modules/container_apps"
  prefix                     = module.naming.prefix
  resource_group_name        = data.azurerm_resource_group.this.name
  location                   = var.location
  log_analytics_workspace_id = module.observability.log_analytics_workspace_id
  registry_id                = data.azurerm_container_registry.this.id
  registry_login_server      = data.azurerm_container_registry.this.login_server
  key_vault_id               = module.keyvault.id
  key_vault_uri              = module.keyvault.uri
  database_url_secret_id     = module.postgres.database_url_secret_id
  apps_enabled               = var.apps_enabled
  image_tag                  = var.image_tag
  redis_image                = var.redis_image
  redis_password_version     = var.redis_password_version
  worker_key_vault_secrets   = var.worker_key_vault_secrets
  tags                       = local.tags
}

module "alerts" {
  source              = "../../modules/alerts"
  prefix              = module.naming.prefix
  resource_group_name = data.azurerm_resource_group.this.name
  action_group_id     = module.observability.action_group_id
  app_ids             = module.container_apps.app_ids
  postgres_id         = module.postgres.id
  tags                = local.tags
}

module "storage" {
  source = "../../modules/storage"
  count  = var.enable_app_blob ? 1 : 0

  name                        = "stsfstgapp${module.naming.suffix}"
  resource_group_name         = data.azurerm_resource_group.this.name
  location                    = var.location
  reader_writer_principal_ids = [module.container_apps.apps_identity_principal_id]
  tags                        = local.tags
}
