# Key Vault (Standard, RBAC mode). Holds the secrets the apps read through Key Vault references:
# those Terraform generates (write-only, never in state) and those people enter by hand (LLM
# provider keys). Staging: 7-day soft delete and no purge protection, so a rebuilt environment can
# reuse the name.

variable "name" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "tenant_id" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

resource "azurerm_key_vault" "this" {
  name                       = var.name
  resource_group_name        = var.resource_group_name
  location                   = var.location
  tenant_id                  = var.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
  # Public endpoint: Container Apps on the Consumption plan without a VNet reaches it over the
  # internet, authenticated by managed identity (RBAC). A private endpoint needs a VNet (production).
  public_network_access_enabled = true
  tags                          = var.tags
}

output "id" {
  value = azurerm_key_vault.this.id
}

output "uri" {
  value = azurerm_key_vault.this.vault_uri
}
