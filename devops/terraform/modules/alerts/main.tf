# Spend-rate guards: Azure Monitor metric alerts that work on any offer (Azure for Students has no
# Cost Management budgets). They do not read the bill; they catch the two ways staging could burn
# the credit fast (devops/terraform/README.md, "Budget"):
#   - the worker stays up a full hour (a stuck queue keeps it at 1 vCPU / 2 GiB);
#   - web or api stays up 6 hours (something keeps them warm);
# and Postgres storage above 80% (it does not grow on its own; a full disk stops writes).
# Metric windows can only be PT1M..PT1H, PT6H, PT12H or P1D.

variable "prefix" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "action_group_id" {
  description = "From modules/observability; null disables every alert here."
  type        = string
  default     = null
}

variable "app_ids" {
  description = "Container app ids by role: web, api, worker (redis is always up by design)."
  type        = map(string)
}

variable "postgres_id" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  enabled = var.action_group_id != null
  # role => [window, frequency]: alert when the minimum replica count stayed above 0 for the window.
  replica_guards = {
    for role, window in { worker = "PT1H", web = "PT6H", api = "PT6H" } :
    role => window if contains(keys(var.app_ids), role)
  }
}

resource "azurerm_monitor_metric_alert" "replicas_up" {
  for_each = local.enabled ? local.replica_guards : {}

  name                = "alert-${var.prefix}-${each.key}-up-${lower(each.value)}"
  resource_group_name = var.resource_group_name
  scopes              = [var.app_ids[each.key]]
  description         = "${each.key} has had at least one replica for ${each.value}: it is billed the whole time. Check what keeps it up."
  severity            = 2
  window_size         = each.value
  frequency           = each.value == "PT1H" ? "PT15M" : "PT1H"
  tags                = var.tags

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "Replicas"
    aggregation      = "Minimum"
    operator         = "GreaterThan"
    threshold        = 0
  }

  action {
    action_group_id = var.action_group_id
  }
}

resource "azurerm_monitor_metric_alert" "postgres_storage" {
  count = local.enabled ? 1 : 0

  name                = "alert-${var.prefix}-postgres-storage-80"
  resource_group_name = var.resource_group_name
  scopes              = [var.postgres_id]
  description         = "Postgres storage is above 80% of the provisioned 32 GiB."
  severity            = 2
  window_size         = "PT1H"
  frequency           = "PT15M"
  tags                = var.tags

  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = "storage_percent"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = 80
  }

  action {
    action_group_id = var.action_group_id
  }
}
