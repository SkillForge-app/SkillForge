# The container registry (ACR Basic, about $5.07/month). Created by bootstrap/, not by
# envs/<environment>/: images are pushed before the first apply that creates the container apps.
# Admin user off: pushes use the GitHub deploy identity (AcrPush), pulls the apps' identity (AcrPull).

variable "name" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

resource "azurerm_container_registry" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = var.tags
}

output "id" {
  value = azurerm_container_registry.this.id
}

output "login_server" {
  value = azurerm_container_registry.this.login_server
}
