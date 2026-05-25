terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  subscription_id = var.subscription_id
  features {}
}

variable "subscription_id" {
  type        = string
  description = "Subscription to deploy the portal infrastructure"
}

variable "location" {
  type    = string
  default = "southeastasia"
}

variable "resource_group_name" {
  type    = string
  default = "TerraformPortal-RG"
}

variable "allowed_ips" {
  type        = list(string)
  description = "Office IPs allowed to access the portal"
  default     = ["103.79.155.206", "103.154.140.246"]
}

# Resource Group
resource "azurerm_resource_group" "portal" {
  name     = var.resource_group_name
  location = var.location
}

# Resource Group for ACI containers (keeps portal RG clean)
resource "azurerm_resource_group" "aci" {
  name     = "${var.resource_group_name}-ACI"
  location = var.location
}

# ============================================================
# Storage Account (logs, state, file share for templates)
# ============================================================
resource "azurerm_storage_account" "portal" {
  name                     = "tfportal${substr(md5(azurerm_resource_group.portal.id), 0, 10)}"
  resource_group_name      = azurerm_resource_group.portal.name
  location                 = azurerm_resource_group.portal.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

# Blob container for deployment logs
resource "azurerm_storage_container" "logs" {
  name                  = "deployment-logs"
  storage_account_name  = azurerm_storage_account.portal.name
  container_access_type = "private"
}

# Blob container for terraform state files (per deployment)
resource "azurerm_storage_container" "tfstate" {
  name                  = "tfstate"
  storage_account_name  = azurerm_storage_account.portal.name
  container_access_type = "private"
}

# File Share for terraform templates (mounted into ACI)
resource "azurerm_storage_share" "templates" {
  name                 = "templates"
  storage_account_name = azurerm_storage_account.portal.name
  quota                = 1 # 1 GB is plenty for .tf files
}

# ============================================================
# User-Assigned Managed Identity for ACI (Terraform executor)
# ============================================================
resource "azurerm_user_assigned_identity" "terraform_runner" {
  name                = "tf-runner-identity"
  resource_group_name = azurerm_resource_group.portal.name
  location            = azurerm_resource_group.portal.location
}

# Grant Contributor on the subscription so ACI can deploy resources
resource "azurerm_role_assignment" "aci_contributor" {
  scope                = "/subscriptions/${var.subscription_id}"
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.terraform_runner.principal_id
}

# ============================================================
# Function App (thin API layer)
# ============================================================
resource "azurerm_service_plan" "functions" {
  name                = "tf-portal-plan"
  resource_group_name = azurerm_resource_group.portal.name
  location            = azurerm_resource_group.portal.location
  os_type             = "Linux"
  sku_name            = "Y1"
}

resource "azurerm_linux_function_app" "api" {
  name                = "tf-runner-${substr(md5(azurerm_resource_group.portal.id), 0, 8)}"
  resource_group_name = azurerm_resource_group.portal.name
  location            = azurerm_resource_group.portal.location
  service_plan_id     = azurerm_service_plan.functions.id

  storage_account_name       = azurerm_storage_account.portal.name
  storage_account_access_key = azurerm_storage_account.portal.primary_access_key

  site_config {
    application_stack {
      python_version = "3.11"
    }

    cors {
      allowed_origins = [
        "https://${azurerm_static_web_app.portal.default_host_name}"
      ]
    }

    dynamic "ip_restriction" {
      for_each = var.allowed_ips
      content {
        name       = "Office-IP-${ip_restriction.key + 1}"
        ip_address = "${ip_restriction.value}/32"
        action     = "Allow"
        priority   = 100 + ip_restriction.key * 10
      }
    }
  }

  app_settings = {
    "FUNCTIONS_WORKER_RUNTIME"       = "python"
    "FUNCTIONS_EXTENSION_VERSION"    = "~4"
    "AzureWebJobsFeatureFlags"       = "EnableWorkerIndexing"
    "SCM_DO_BUILD_DURING_DEPLOYMENT" = "true"
    # Storage
    "STORAGE_CONNECTION_STRING" = azurerm_storage_account.portal.primary_connection_string
    "STORAGE_ACCOUNT_NAME"     = azurerm_storage_account.portal.name
    "STORAGE_ACCOUNT_KEY"      = azurerm_storage_account.portal.primary_access_key
    "LOGS_CONTAINER"           = "deployment-logs"
    "TFSTATE_CONTAINER"        = "tfstate"
    "TEMPLATES_SHARE"          = "templates"
    # ACI config
    "ACI_RESOURCE_GROUP"  = azurerm_resource_group.aci.name
    "ACI_LOCATION"        = var.location
    "ACI_SUBSCRIPTION_ID" = var.subscription_id
    # Managed Identity for Terraform inside ACI
    "ARM_USE_MSI"       = "true"
    "ARM_CLIENT_ID"     = azurerm_user_assigned_identity.terraform_runner.client_id
    "ARM_TENANT_ID"     = azurerm_user_assigned_identity.terraform_runner.tenant_id
    "ARM_SUBSCRIPTION_ID" = var.subscription_id
    "ACI_IDENTITY_ID"   = azurerm_user_assigned_identity.terraform_runner.id
  }

  identity {
    type = "SystemAssigned"
  }
}

# Function App needs Contributor on RG to create/delete ACI containers
resource "azurerm_role_assignment" "function_contributor_rg" {
  scope                = azurerm_resource_group.portal.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_linux_function_app.api.identity[0].principal_id
}

# Function App needs Contributor on ACI RG to create/delete containers there
resource "azurerm_role_assignment" "function_contributor_aci_rg" {
  scope                = azurerm_resource_group.aci.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_linux_function_app.api.identity[0].principal_id
}

# Function App needs Reader on subscription for check-subscription
resource "azurerm_role_assignment" "function_reader" {
  scope                = "/subscriptions/${var.subscription_id}"
  role_definition_name = "Reader"
  principal_id         = azurerm_linux_function_app.api.identity[0].principal_id
}

# ============================================================
# Static Web App (frontend)
# ============================================================
resource "azurerm_static_web_app" "portal" {
  name                = "tf-portal-web"
  resource_group_name = azurerm_resource_group.portal.name
  location            = "eastasia"
  sku_tier            = "Free"
  sku_size            = "Free"
}

# ============================================================
# Auto-deploy code
# ============================================================
resource "null_resource" "deploy_function_code" {
  triggers = {
    function_app_id = azurerm_linux_function_app.api.id
    code_hash       = filemd5("${path.module}/../functions/function_app.py")
  }

  provisioner "local-exec" {
    command     = "Remove-Item '${path.module}/../functions.zip' -Force -ErrorAction SilentlyContinue; Compress-Archive -Path '${path.module}/../functions/*' -DestinationPath '${path.module}/../functions.zip' -Force; az functionapp deployment source config-zip --resource-group ${var.resource_group_name} --name ${azurerm_linux_function_app.api.name} --src '${path.module}/../functions.zip' --build-remote true"
    interpreter = ["powershell", "-Command"]
  }

  depends_on = [
    azurerm_linux_function_app.api,
    azurerm_role_assignment.function_contributor_rg,
    azurerm_role_assignment.function_reader
  ]
}

resource "null_resource" "deploy_frontend" {
  triggers = {
    static_app_id = azurerm_static_web_app.portal.id
    code_hash     = filemd5("${path.module}/../frontend/app.js")
  }

  provisioner "local-exec" {
    command     = "swa deploy '${path.module}/../frontend' --deployment-token ${azurerm_static_web_app.portal.api_key} --env production"
    interpreter = ["powershell", "-Command"]
  }

  depends_on = [
    azurerm_static_web_app.portal,
    null_resource.deploy_function_code
  ]
}

# Upload templates to File Share
resource "null_resource" "upload_templates" {
  triggers = {
    share_id  = azurerm_storage_share.templates.id
    t01_hash  = filemd5("${path.module}/../../01 Windows SQL Server/main.tf")
    t02_hash  = filemd5("${path.module}/../../02 Windows SQL w Dynamics GP/main.tf")
    script_hash = filemd5("${path.module}/../scripts/deploy.sh")
  }

  provisioner "local-exec" {
    command     = <<-EOT
      az storage file upload-batch --destination templates --source "${replace(path.module, "/", "\\")}\..\..\01 Windows SQL Server" --destination-path "01" --account-name ${azurerm_storage_account.portal.name} --account-key "${azurerm_storage_account.portal.primary_access_key}" --pattern "*.tf"
      az storage file upload-batch --destination templates --source "${replace(path.module, "/", "\\")}\..\..\02 Windows SQL w Dynamics GP" --destination-path "02" --account-name ${azurerm_storage_account.portal.name} --account-key "${azurerm_storage_account.portal.primary_access_key}" --pattern "*.tf"
      az storage file upload-batch --destination templates --source "${replace(path.module, "/", "\\")}\..\..\02 Windows SQL w Dynamics GP\scripts" --destination-path "02/scripts" --account-name ${azurerm_storage_account.portal.name} --account-key "${azurerm_storage_account.portal.primary_access_key}" --pattern "*.ps1"
      az storage file upload --share-name templates --source "${replace(path.module, "/", "\\")}\..\scripts\deploy.sh" --path "deploy.sh" --account-name ${azurerm_storage_account.portal.name} --account-key "${azurerm_storage_account.portal.primary_access_key}"
    EOT
    interpreter = ["powershell", "-Command"]
  }

  depends_on = [azurerm_storage_share.templates]
}

# ============================================================
# Outputs
# ============================================================
output "static_web_app_url" {
  value = "https://${azurerm_static_web_app.portal.default_host_name}"
}

output "function_app_url" {
  value = "https://${azurerm_linux_function_app.api.default_hostname}"
}

output "function_app_name" {
  value = azurerm_linux_function_app.api.name
}

output "storage_account_name" {
  value = azurerm_storage_account.portal.name
}

output "aci_identity_client_id" {
  value = azurerm_user_assigned_identity.terraform_runner.client_id
}

output "static_web_app_api_key" {
  value     = azurerm_static_web_app.portal.api_key
  sensitive = true
}
