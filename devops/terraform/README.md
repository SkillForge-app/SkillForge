# devops/terraform/: staging on Azure (OPS-04)

Staging runs on **Azure for Students**: $100 of credit and no card. When the credit runs out, the subscription is disabled. There is never a bill.

- **What it has to cover:** at least 25 Nov to 31 Dec 2026 (the project deadline is 15 Dec).
- **Where the numbers come from:** Microsoft's docs and the public Azure Retail Prices API, read on 18 Nov 2026. Prices are USD, East US, 730 h a month. Other regions differ a little.

Nothing here has been applied yet. The account isn't chosen (see [First deploy](#first-deploy)).

## Layout

| Path | What it is | Run by |
|---|---|---|
| `bootstrap/` | Run once. It creates the state storage account, the `rg-skillforge-staging` resource group, the container registry, and the GitHub deploy identity (OIDC) with its role assignments. Its state is local and git-ignored. | A person with Owner rights (`az login`) |
| `envs/staging/` | Everything else: Container Apps, Postgres, Key Vault, logs, cost alerts, and optionally blob storage. Its state lives in Azure Storage. | The deploy workflow (`.github/workflows/deploy-staging.yml`) |
| `envs/production/` | Later | |
| `modules/naming` | Names shared by bootstrap and the environments. Globally unique names end in `sha1(subscription id)[:8]`. | |
| `modules/registry` | ACR Basic, admin user off | Called from bootstrap |
| `modules/keyvault` | Key Vault Standard in RBAC mode, 7-day soft delete | |
| `modules/postgres` | Flexible Server B1ms, PG 18, 32 GiB, `azure.extensions=VECTOR`; the admin password goes to Key Vault | |
| `modules/container_apps` | The environment (Consumption profile): web, api, worker, redis, the migrate job, and the apps' identity | |
| `modules/observability` | Log Analytics with a daily cap, the alert action group, and an optional budget | |
| `modules/alerts` | Spend-rate guards: metric alerts on replicas, and Postgres storage | |
| `modules/storage` | App blob storage, only when `enable_app_blob = true` (default `false`) | |
| `backend-config.sh` | Prints the `terraform init -backend-config` arguments for a subscription | |

**Versions:**
- **The two-week rule:**
  - Terraform **1.17.1** (released 28 Oct 2026);
  - `hashicorp/azurerm` **5.12.0** (29 Oct 2026);
  - `hashicorp/random` **3.9.1** (11 Sep 2026).
- **Pins:** all three are exact pins. The `.terraform.lock.hcl` files are committed, with hashes for Linux, Windows and macOS.

**Secrets never touch the state:**
- The Postgres and redis passwords are **ephemeral** values, sent only to write-only arguments (the server's `administrator_password_wo`, and Key Vault's `value_wo`).
- To rotate one, bump `postgres_password_version` / `redis_password_version`.
- LLM provider keys are typed into Key Vault by hand, and never into Terraform.

## Services and cost

| Component | Choice | $/month |
|---|---|---|
| web, api, worker | **Container Apps**, Consumption plan, max 1 replica each, scale to zero. web: 0.25 vCPU / 0.5 GiB. api: 0.5 / 1 GiB. worker: 1 / 2 GiB, started by a KEDA `redis` rule on `rq:queue:skills` | the ACA line |
| redis | **A container app**: compose's pinned `redis:8.8.2-alpine`, internal TCP on port 6379, 1 replica, no persistence. 0.25 vCPU / 0.5 GiB | the ACA line |
| migrations | **A Container Apps job** (the api image), `alembic upgrade head`, started by each deploy | the ACA line |
| **ACA line** | Free each month per subscription: 180,000 vCPU-s, 360,000 GiB-s and 2M requests | **likely ≈ 5.5, planning ≈ 27.5** |
| Postgres | **Flexible Server B1ms, PG 18**, 32 GiB, 7-day backups (free up to the 32 GiB provisioned) | **16.09** (12.41 + 3.68) |
| Registry | **ACR Basic** | **5.07** |
| Blob | StorageV2 Hot LRS ($0.0208/GB): the state account; the app account only if enabled | **≤ 0.15** |
| Key Vault | Standard ($0.03 per 10K operations) | **< 0.01** |
| Logs | Log Analytics with a 0.1 GB/day cap. The first 5 GB/month per billing account and 31 days of retention are free | **0** |
| Cost alerts | 4 metric alert rules | **≤ 0.50** (the rule price is not fetched yet) |

**How the ACA line is worked out.** The rates are $0.000024 per active vCPU-s, $0.000003 per idle vCPU-s, and $0.000003 per GiB-s.
- **Likely, ≈ $5.5:**
  - web and api are up 1 h a day, the worker 15 min a day;
  - redis bills at the idle rate (a replica is idle at its minimum count, under 0.01 vCPU and under 1,000 B/s).
- **Planning, ≈ $27.5:** web and api up 4 h a day, the worker 1 h a day, and redis billed at the active rate.

**Why these choices:**
- **Container Apps, not App Service:**
  - App Service B1 Linux is $12.41/month whether anyone uses it or not.
  - Container Apps bills nothing when an app is scaled to zero, scales the worker from the queue, runs migrations as a job, and runs the same images as compose.
- **Postgres Flexible, not Postgres in a container:**
  - Container Apps has no persistent disk: only ephemeral storage, or Azure Files over SMB or NFS.
- **Redis in a container, not Azure Cache:**
  - Azure Cache Basic C0 costs $16.06/month, and Basic/Standard/Premium retire on 30 Sep 2028.
  - A container costs $2–16/month.
  - Internal TCP ingress works without a VNet; only external TCP needs one.

## Budget, 25 Nov–31 Dec 2026 (37 days)

| Case | $/month | Per day | 25 Nov–31 Dec | Credit left on 31 Dec |
|---|---|---|---|---|
| Likely | ≈ 27 | ≈ 0.89 | **≈ $33** | ≈ $67 |
| Planning | ≈ 49 | ≈ 1.61 | **≈ $60** | ≈ $40 |
| Runaway: every app active 24/7 at max 1 replica | ≈ 173 | ≈ 5.69 | the $100 is gone in about **17.6 days** | 0 |

**Alerts at 50/80/100%.** Azure Cost Management lists **Azure for Students (MS-AZR-0170P) as not supported**, so standard budgets are expected not to work. The setup is:
1. **`enable_budget`** (default `false`): a $100 budget with emails at 50/80/100% of actual cost and 100% of forecast. Turn it on only if manual step 4 shows Budgets working.
2. **Spend-rate guards** (`modules/alerts`, which work on any offer). Each sends an email when:
   - the worker has kept a replica for 1 h;
   - web or api has kept one for 6 h;
   - Postgres storage is above 80%.
   - Max 1 replica per app bounds the worst case.
3. **The weekly credit check** (manual step 9). The remaining credit shows in the portal's **Education → Overview** and in the Microsoft Azure Sponsorships portal. What each threshold triggers:
   - **$50 used:** review the usage.
   - **$80 used:** stop Postgres at night, shrink the worker, and prepare the fallback.
   - **$100 used:** the subscription is disabled.

## Compatibility

**Postgres and pgvector:**
- **PG 18** is offered on Flexible Server (minor 18.6). Its PG 18 limitations don't affect us:
  - some extensions aren't on 18 yet, but `vector` is, and it's the only extension the repo uses;
  - there's no `io_method=io_uring`, and the repo sets no `io_method`.
- **The pgvector mismatch:**
  - Azure ships `vector` **0.8.7** on PG 13–18, with HNSW and IVFFlat. Local and CI run **0.8.6** (`compose.yaml`).
  - It's a patch-level difference, and HNSW exists in both. `CREATE EXTENSION vector` (no `VERSION`) gets 0.8.7. Staging starts empty, so no index moves between the two.
  - **The impact:** a 0.8.7 behaviour change would show up only on staging.
  - **Follow-up:** move compose and CI to a `pgvector:0.8.7-pg18` image once one is at least 14 days old.

**What Azure needs that compose doesn't:**
- `azure.extensions=VECTOR` (set by Terraform) before `CREATE EXTENSION`.
- The admin role is `azure_pg_admin`, not a superuser.
- **No initdb hook.** Compose's first-start step (pgvector, then DE's `data/db/` SQL, with `roles-local.sql`'s dev password) becomes a database bootstrap step in the deploy (OPS-06). Its passwords come from Key Vault.

**The model is baked into the worker image** (`worker.Dockerfile`, target `baked`), not put on Azure Files.
- **Why not Azure Files:**
  - Container Apps can mount Azure Files read-only, but SMB needs the storage account key (a long-lived key) unless we use managed-identity auth, which is still in preview;
  - NFS needs a VNet.
- **What baking costs:** 66 MB on a 1.34 GB image.

## First deploy

Run these in order.
1. **Sign up for Azure for Students** with a school email (one account per person). Check the $100 credit under **Education → Overview**.
2. **Note the Subscription ID and Tenant ID** (Subscriptions blade).
3. **Find the allowed regions:** Subscription → Policies → Assignments → "Allowed resource deployment regions" / "Allowed locations". Note the list, then pick the closest region that offers Postgres Flexible B1ms with PG 18 (the create blade shows it; don't create anything).
4. **Check budgets:** Cost Management → Budgets. Does it open, or say the offer isn't supported? If it opens, set `enable_budget = true` later.
5. **Register these resource providers** (Subscription → Resource providers): Microsoft.App, Microsoft.ContainerRegistry, Microsoft.DBforPostgreSQL, Microsoft.OperationalInsights, Microsoft.Insights, Microsoft.KeyVault, Microsoft.Storage, Microsoft.ManagedIdentity.
6. **Bootstrap**, as the account owner. Its state stays in `bootstrap/` and is git-ignored, so keep the folder.
   ```
   az login --tenant <tenant id>
   terraform -chdir=devops/terraform/bootstrap init
   terraform -chdir=devops/terraform/bootstrap apply \
     -var subscription_id=<id> -var tenant_id=<id> -var location=<region>
   ```
7. **GitHub** (an org owner):
   - create the environment **`staging`**, deployment branches `main` only, no required reviewer;
   - add bootstrap's `github_environment_secrets` (`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`) as environment secrets;
   - set the repository variable `STAGING_DEPLOY_ENABLED=true` to switch the deploy workflow on.
8. **First run** with `location` set in `staging.tfvars` and `apps_enabled = false`. The workflow creates the database, vault, logs and the Container Apps environment.
   - Then set the `staging` environment variable `STAGING_API_URL` to the `api_url` output (it's baked into the web image).
9. **Turn the apps on:** set `apps_enabled = true` in a PR. The next run builds the three images, creates the apps with them, runs the migrate job, and smoke-tests.
10. **AI's secrets:** AI enters the LLM provider keys into Key Vault (`az keyvault secret set`), and they're listed in `worker_key_vault_secrets`.
11. **Every Monday:** the credit check.

**Switching to another account:**
- Change `location` in `staging.tfvars` and the three GitHub environment secrets.
- Run bootstrap for the new subscription.
- The names follow the subscription id, so nothing else changes.

## Checks

- **CI** (`terraform-check` in `.github/workflows/terraform.yml`):
  - `terraform fmt -check` and `validate` with `-backend=false`;
  - no Azure credentials and no plan on PRs, because a PR's workflow code could read the state.
- **Trivy's `fs` scan** reports misconfigurations in these files.
- **By hand:**
  ```
  terraform fmt -check -recursive devops/terraform
  terraform -chdir=devops/terraform/envs/staging init -backend=false && terraform -chdir=devops/terraform/envs/staging validate
  ```

## Risks and fallback

| # | Risk | Mitigation |
|---|---|---|
| R1 | The region policy blocks East US, or B1ms/PG 18 is missing from the allowed regions | Step 3; prices differ a little by region |
| R2 | No budgets on this offer | The guards and the weekly check above |
| R3 | The credit runs out, so the subscription is disabled | Planning ≈ $60 to 31 Dec; stop Postgres at night; the fallback below |
| R4 | One student's login holds all of staging | Deploys go only through GitHub; staging is rebuildable from Terraform, migrations and seeds |
| R5 | Redis has no persistence, so queued jobs are lost on a restart | Fine for staging; Azure Cache C0 ($16) if it matters |
| R6 | Worker cold start (a 1.4 GB pull plus the model load; KEDA polls every 30 s) | Not measured yet; set `min_replicas = 1` on demo days |
| R7 | pgvector 0.8.7 on Azure vs 0.8.6 in tests | The follow-up above |
| R8 | Postgres public access: the "Azure services" rule admits any Azure address | TLS required, a generated 40-character password, staging data only; production gets a VNet |
| R9 | Secrets in the state | None: write-only and ephemeral. The state account is AAD-only with versioning |
| R10 | DE's SQL vs Backend's Alembic on an empty database | The bootstrap step follows compose's order; DE and Backend confirm who owns which tables |

**The fallback, in order:**
1. **Another teammate's Azure for Students subscription:** switch accounts (above), about 30–45 min, with a fresh $100.
2. **One VM running `compose.yaml`:** Linux B2als v2 ($0.0376/h, ≈ $27.45/month, 2 vCPU / 4 GiB) or B2s ($0.0416/h), plus a disk and a TLS proxy. Deploys go through `az vm run-command` over OIDC, with no SSH keys.
3. **App Service B1 Linux** ($12.41/month) for web and api, if Container Apps itself is the problem.

## Sources (read 18 Nov 2026)

- Container Apps:
  - [billing](https://learn.microsoft.com/azure/container-apps/billing)
  - [scaling](https://learn.microsoft.com/azure/container-apps/scale-app)
  - [ingress](https://learn.microsoft.com/azure/container-apps/ingress-overview)
  - [secrets](https://learn.microsoft.com/azure/container-apps/manage-secrets)
  - [storage mounts](https://learn.microsoft.com/azure/container-apps/storage-mounts)
- Postgres:
  - [versions](https://learn.microsoft.com/azure/postgresql/flexible-server/concepts-supported-versions)
  - [extension versions](https://learn.microsoft.com/azure/postgresql/extensions/concepts-extensions-versions)
  - [backups](https://learn.microsoft.com/azure/postgresql/backup-restore/concepts-backup-restore)
- [GitHub OIDC with a user-assigned identity](https://learn.microsoft.com/azure/developer/github/connect-from-azure-openid-connect)
- Prices: [Azure Monitor pricing](https://azure.microsoft.com/pricing/details/monitor/) and the Retail Prices API (`prices.azure.com`).
