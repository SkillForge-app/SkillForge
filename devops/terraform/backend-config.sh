#!/usr/bin/env bash
# Prints the -backend-config arguments for `terraform init` in envs/<environment>/, derived from the
# subscription id the same way modules/naming does (the first 8 hex characters of its sha1), so no
# account-specific value is committed:
#   terraform -chdir=devops/terraform/envs/staging init $(devops/terraform/backend-config.sh "$SUB")
set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  echo "usage: $0 <subscription-id>" >&2
  exit 2
fi
suffix="$(printf '%s' "$1" | sha1sum | cut -c1-8)"
printf '%s\n' \
  "-backend-config=resource_group_name=rg-skillforge-tfstate" \
  "-backend-config=storage_account_name=stsftfstate${suffix}"
