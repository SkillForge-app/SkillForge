# Staging settings (no secrets, no subscription or tenant id: CI passes those from the GitHub
# environment secrets as TF_VAR_subscription_id and TF_VAR_tenant_id).
#
# The account is not chosen yet. When it is (devops/terraform/README.md, manual steps 1-7):
#   1. set `location` to a region its "Allowed locations" policy permits (the same as bootstrap's);
#   2. leave apps_enabled = false for the first deploy (no image exists yet), then set it to true.

# location = "<allowed region, e.g. eastus>"

apps_enabled    = false
enable_app_blob = false
enable_budget   = false

# alert_emails = ["<devops owner address>"]

# Added once the secrets exist in Key Vault (entered by hand):
# worker_key_vault_secrets = {
#   SKILLFORGE_PGVECTOR_DSN = "pgvector-dsn"
# }
