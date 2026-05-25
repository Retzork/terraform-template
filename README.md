# Azure Infrastructure Templates & Self-Service Portal

This repository contains Terraform templates for deploying Azure infrastructure, and a self-service web portal that allows company users to deploy resources without needing Terraform knowledge or Azure Portal access.

## Structure

```
template/
├── 01 Windows SQL Server/          # Template: Standalone SQL Server VM
├── 02 Windows SQL w Dynamics GP/   # Template: SQL + Dynamics GP from custom image
└── portal/                         # Self-service deployment portal
    ├── frontend/                   # Azure Static Web App (HTML/CSS/JS)
    ├── functions/                  # Azure Function App (Python API)
    ├── scripts/                    # Scripts that run inside ACI containers
    └── terraform/                  # IaC for the portal infrastructure itself
```

## Templates

### 01 - Windows SQL Server
Standalone Windows Server 2019 VM with SQL Server 2017 Developer. Includes:
- Configurable OS, data, and log disks
- Public IP with RDP access (office IPs only)
- Custom RDP user creation

### 02 - Windows SQL + Dynamics GP
Windows VM with SQL Server and Dynamics GP 2018 pre-installed from a Shared Image Gallery. Includes:
- Custom image from gallery (GP2018SQL)
- SQL mixed mode, ODBC DSN auto-configured
- Configurable data/log disks
- Custom RDP user creation

Both templates have NSG rules that restrict RDP access to office IPs only (103.79.155.206, 103.154.140.246).

---

## Portal

The portal is a serverless web application that gives users a simple UI to deploy, monitor, and destroy Azure infrastructure.

### Architecture

```
User Browser
    │
    ▼
Azure Static Web App (Free) ─── frontend/
    │
    ▼ API calls
Azure Function App (Consumption/Y1) ─── functions/
    │
    ▼ Creates container
Azure Container Instance (hashicorp/terraform:1.9)
    │
    ▼ terraform apply/destroy
Azure Resources (target subscription)
```

**Cost when idle: ~$0/month** (Free SWA + Consumption Functions + ephemeral ACI)

### How It Works

1. User picks a template on the landing page
2. Fills in a form (VM name, size, disks, credentials, subscription, resource group)
3. Clicks "Deploy Now" — the Function App:
   - Derives a **Stack ID**: `{template}/{subscription}.{resource_group}`
   - Saves variables to blob storage
   - Uploads terraform.tfvars to Azure File Share
   - Spins up an ACI container with Terraform
4. ACI container runs `terraform init` (with remote backend) then `apply`
5. Logs stream in real-time to the file share — user refreshes to see progress
6. On completion, outputs (public IP, VM name, RDP username) are displayed

### Stack ID

Every deployment is identified by a **Stack ID** — a stable identifier that never changes across apply/destroy/re-apply:

```
{template_id}/{subscription_id}.{resource_group_name}
```

Example: `01/dfaa40f0-0f72-4980-bd34-ccf9162a757d.SQL-RG`

This ID is used to:
- Track the Terraform state file
- Store deployment variables (for destroy)
- View logs and resource status
- Trigger destroy operations

### State Management

Terraform state is stored remotely in Azure Blob Storage:
- Container: `tfstate`
- Key: `{stack_id}.tfstate`

This means:
- Re-deploying to the same RG updates resources instead of failing
- Destroy works because Terraform knows what to tear down
- Different subscriptions with the same RG name are separate stacks

### Portal Pages

| Page | Purpose |
|------|---------|
| `index.html` | Landing — pick a template or search by Stack ID |
| `form.html` | Configure deployment — subscription check, RG check, form fields |
| `logs.html` | Real-time terraform output, collapsible when complete |
| `resources.html` | Resource checker — view state-tracked resources by Stack ID |

### API Endpoints

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/templates` | GET | List available templates |
| `/api/check-subscription` | POST | Verify managed identity can access a subscription |
| `/api/check-resource-group` | POST | Check if an RG already exists |
| `/api/deploy` | POST | Trigger terraform apply via ACI |
| `/api/destroy` | POST | Trigger terraform destroy via ACI |
| `/api/status/{stack_id}` | GET | Get latest operation logs |
| `/api/check-resources/{stack_id}` | GET | Read terraform state and list resources |

### Security

- Function App is IP-restricted to office IPs
- RDP NSG rules only allow office IPs
- Admin credentials are hidden from all user-facing outputs
- Passwords are stored in a separate secure blob (not in logs)
- ACI uses a User-Assigned Managed Identity with Contributor on the subscription

### Deploying the Portal

```powershell
cd portal/terraform
terraform init
terraform apply
```

This creates all portal infrastructure and auto-deploys:
- Function App code (zipped and deployed)
- Frontend (deployed via `swa` CLI)
- Templates uploaded to Azure File Share

### Adding a New Template

1. Create a new folder (e.g., `03 My Template/`) with `.tf` files
2. Add `backend "azurerm" {}` to the `terraform` block in `providers.tf`
3. Add the template definition to:
   - `portal/functions/function_app.py` → `TEMPLATES` dict
   - `portal/frontend/app.js` → `TEMPLATES` object (with form field definitions)
4. Add a card to `portal/frontend/index.html`
5. Update `portal/terraform/main.tf` → `null_resource.upload_templates` to upload the new template to the file share
6. Run `terraform apply` in `portal/terraform`

### Resource Checker

The Resource Checker page (`resources.html`) lets users view their deployed resources by Stack ID. It reads the Terraform state file and displays:
- Resource list (VMs, disks, NICs, IPs, etc.)
- Outputs (public IP, VM name, RDP username)
- Last operation status

**Important**: The state file only tracks changes made through this portal. Manual changes in Azure Portal (resizing VMs, deleting resources, etc.) are not reflected here.
