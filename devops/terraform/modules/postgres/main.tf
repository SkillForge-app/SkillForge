# Azure Database for PostgreSQL flexible server: Burstable B1ms, PostgreSQL 18, 32 GiB, 7-day
# backups (free up to the provisioned 32 GiB). About $16.09/month in East US.
#
# pgvector: Azure ships `vector` 0.8.7 on PG 18 (local and CI: 0.8.6, see devops/terraform/README.md).
# It must be allow-listed (azure.extensions) before `CREATE EXTENSION vector`, which the admin
# (azure_pg_admin, not a superuser) can then run.
#
# The admin password is generated as an EPHEMERAL value and sent only to write-only arguments (the
# server and Key Vault), so it is never stored in the Terraform state or plan. It is sent again
# only when password_version changes (bump it to rotate).

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

variable "name" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "key_vault_id" {
  description = "Where the admin password and the database URL are written."
  type        = string
}

variable "sku_name" {
  type    = string
  default = "B_Standard_B1ms"
}

variable "storage_mb" {
  type    = number
  default = 32768
}

variable "database_name" {
  type    = string
  default = "skillforge"
}

variable "administrator_login" {
  type    = string
  default = "sfadmin"
}

variable "password_version" {
  description = "Bump to generate and send a new admin password (rotation)."
  type        = number
  default     = 1
}

variable "tags" {
  type    = map(string)
  default = {}
}

ephemeral "random_password" "admin" {
  length  = 40
  special = false
}

resource "azurerm_postgresql_flexible_server" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  version             = "18"
  sku_name            = var.sku_name
  storage_mb          = var.storage_mb

  backup_retention_days        = 7
  geo_redundant_backup_enabled = false

  # Public access with TLS required (the default require_secure_transport=on) and the "Azure
  # services" firewall rule below. Staging only: production gets VNet integration (risk R8).
  public_network_access_enabled = true

  administrator_login               = var.administrator_login
  administrator_password_wo         = ephemeral.random_password.admin.result
  administrator_password_wo_version = var.password_version

  tags = var.tags

  lifecycle {
    # Azure picks the zone at creation; changing it later would mean a failover.
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_database" "this" {
  name      = var.database_name
  server_id = azurerm_postgresql_flexible_server.this.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# Allow-list pgvector. Without it `CREATE EXTENSION vector` fails on Azure.
resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.this.id
  value     = "VECTOR"
}

# 0.0.0.0-0.0.0.0 means "allow public access from any Azure service within Azure": the Container Apps
# outbound addresses are not fixed on the Consumption plan. It admits ANY Azure tenant's addresses,
# so the password and TLS are what protect the server (risk R8).
resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  name             = "AllowAllAzureServicesAndResourcesWithinAzureIps"
  server_id        = azurerm_postgresql_flexible_server.this.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_key_vault_secret" "admin_password" {
  name             = "pg-admin-password"
  key_vault_id     = var.key_vault_id
  value_wo         = ephemeral.random_password.admin.result
  value_wo_version = var.password_version
}

# The URL the API, the worker and the migrate job read (DATABASE_URL). For now it is the admin
# login: the least-privilege app role is created by the database bootstrap step (OPS-06, risk R10).
resource "azurerm_key_vault_secret" "database_url" {
  name             = "database-url"
  key_vault_id     = var.key_vault_id
  value_wo         = "postgresql+psycopg://${var.administrator_login}:${ephemeral.random_password.admin.result}@${azurerm_postgresql_flexible_server.this.fqdn}:5432/${var.database_name}?sslmode=require"
  value_wo_version = var.password_version
}

output "id" {
  value = azurerm_postgresql_flexible_server.this.id
}

output "fqdn" {
  value = azurerm_postgresql_flexible_server.this.fqdn
}

output "database_url_secret_id" {
  description = "Versionless Key Vault id: apps pick up a new value within 30 minutes."
  value       = azurerm_key_vault_secret.database_url.versionless_id
}
