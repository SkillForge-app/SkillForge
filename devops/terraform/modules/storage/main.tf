# App blob storage: a StorageV2 Hot LRS account (about $0.0208/GB-month) with one private container,
# reached by the apps' managed identity (shared keys off). envs/<environment>/ creates this module
# only when enable_app_blob is true (default false: nothing in the code needs it yet). The Terraform
# state lives in a separate account that bootstrap/ creates.

variable "name" {
  description = "3-24 lowercase letters and digits, globally unique."
  type        = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "container_name" {
  type    = string
  default = "artifacts"
}

variable "reader_writer_principal_ids" {
  description = "Principals given Storage Blob Data Contributor on the container (the apps' identity)."
  type        = list(string)
  default     = []
}

variable "tags" {
  type    = map(string)
  default = {}
}

resource "azurerm_storage_account" "this" {
  name                            = var.name
  resource_group_name             = var.resource_group_name
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
  tags                            = var.tags

  blob_properties {
    delete_retention_policy {
      days = 7
    }

    container_delete_retention_policy {
      days = 7
    }
  }
}

resource "azurerm_storage_container" "this" {
  name                  = var.container_name
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}

resource "azurerm_role_assignment" "blob_contributor" {
  for_each = toset(var.reader_writer_principal_ids)

  scope                = azurerm_storage_container.this.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = each.value
  principal_type       = "ServicePrincipal"
}

output "account_name" {
  value = azurerm_storage_account.this.name
}

output "blob_endpoint" {
  value = azurerm_storage_account.this.primary_blob_endpoint
}

output "container_name" {
  value = azurerm_storage_container.this.name
}
