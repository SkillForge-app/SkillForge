# Logs and cost notifications.
#   - Log Analytics (PerGB2018) with a daily cap: the first 5 GB/month per billing account and 31 days
#     of retention are free, so the cap keeps staging at $0 for logs.
#   - An action group that emails the alert address (used by modules/alerts).
#   - An optional subscription budget ($100, alerts at 50/80/100% actual and 100% forecast). Azure
#     Cost Management does not list Azure for Students (MS-AZR-0170P) as a supported offer, so it is
#     off by default (enable_budget); turn it on only after the portal shows Budgets working (manual
#     step 4 in devops/terraform/README.md).

variable "prefix" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "subscription_id" {
  type = string
}

variable "alert_emails" {
  description = "Who gets the cost-guard and budget emails. Empty: no action group, no emails."
  type        = list(string)
  default     = []
}

variable "log_daily_cap_gb" {
  type    = number
  default = 0.1
}

variable "enable_budget" {
  type    = bool
  default = false
}

variable "budget_amount" {
  description = "In the billing currency (the Azure for Students credit is $100)."
  type        = number
  default     = 100
}

variable "budget_start_date" {
  description = "First day of a month, RFC 3339 (Azure requires the first of the month)."
  type        = string
  default     = "2026-11-01T00:00:00Z"
}

variable "tags" {
  type    = map(string)
  default = {}
}

resource "azurerm_log_analytics_workspace" "this" {
  name                = "log-${var.prefix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = var.log_daily_cap_gb
  tags                = var.tags
}

resource "azurerm_monitor_action_group" "cost" {
  count = length(var.alert_emails) > 0 ? 1 : 0

  name                = "ag-${var.prefix}-cost"
  resource_group_name = var.resource_group_name
  short_name          = "sfcost"
  tags                = var.tags

  dynamic "email_receiver" {
    for_each = var.alert_emails
    content {
      name                    = "email-${email_receiver.key}"
      email_address           = email_receiver.value
      use_common_alert_schema = true
    }
  }
}

resource "azurerm_consumption_budget_subscription" "credit" {
  count = var.enable_budget && length(var.alert_emails) > 0 ? 1 : 0

  name            = "budget-${var.prefix}-credit"
  subscription_id = "/subscriptions/${var.subscription_id}"
  amount          = var.budget_amount
  time_grain      = "Annually"

  time_period {
    start_date = var.budget_start_date
  }

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      enabled        = true
      threshold      = notification.value
      operator       = "GreaterThanOrEqualTo"
      threshold_type = "Actual"
      contact_emails = var.alert_emails
    }
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThanOrEqualTo"
    threshold_type = "Forecasted"
    contact_emails = var.alert_emails
  }
}

output "log_analytics_workspace_id" {
  value = azurerm_log_analytics_workspace.this.id
}

output "action_group_id" {
  description = "null when no alert email is set."
  value       = length(azurerm_monitor_action_group.cost) > 0 ? azurerm_monitor_action_group.cost[0].id : null
}
