terraform {
  # Two-week rule: Terraform 1.17.1 (28 Oct 2026), azurerm 5.12.0 (29 Oct 2026), random 3.9.1
  # (11 Sep 2026). Exact pins; .terraform.lock.hcl (committed) pins the provider checksums.
  required_version = "= 1.17.1"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 5.12.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "= 3.9.1"
    }
  }

  # State in the storage account bootstrap/ created, through Microsoft Entra (no storage keys).
  # resource_group_name and storage_account_name depend on the subscription; pass them at init:
  #   terraform init $(../../backend-config.sh "$ARM_SUBSCRIPTION_ID")
  backend "azurerm" {
    container_name   = "tfstate"
    key              = "staging.tfstate"
    use_azuread_auth = true
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id
  # Providers are registered once by hand (README, manual step 5): the deploy identity has no
  # subscription-wide rights to do it.
  resource_provider_registrations = "none"
  storage_use_azuread             = true
}
