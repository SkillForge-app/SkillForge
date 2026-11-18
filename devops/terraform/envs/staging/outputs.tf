# Read by the deploy workflow (`terraform output -raw <name>`). No secret is an output.

output "resource_group" {
  value = data.azurerm_resource_group.this.name
}

output "registry_login_server" {
  value = data.azurerm_container_registry.this.login_server
}

output "api_url" {
  description = "Baked into the web image as NEXT_PUBLIC_API_BASE_URL. Known once the environment exists."
  value       = module.container_apps.api_url
}

output "web_url" {
  value = module.container_apps.web_url
}

output "app_names" {
  value = module.container_apps.names
}

output "apps_enabled" {
  value = var.apps_enabled
}

output "key_vault_uri" {
  value = module.keyvault.uri
}

output "postgres_fqdn" {
  value = module.postgres.fqdn
}

output "app_blob" {
  description = "null while enable_app_blob is false."
  value = var.enable_app_blob ? {
    account   = module.storage[0].account_name
    endpoint  = module.storage[0].blob_endpoint
    container = module.storage[0].container_name
  } : null
}
