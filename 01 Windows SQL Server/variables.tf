variable "subscription_id" {
  type        = string
  description = "Azure subscription ID to deploy into"
}

variable "resource_group_name" {
  type        = string
  description = "Name of the resource group"
}

variable "location" {
  type        = string
  description = "Azure region for all resources"
}

variable "vm_name" {
  type        = string
  description = "Name of the SQL Server virtual machine"
}

variable "vm_size" {
  type        = string
  description = "Virtual Machine size (e.g. Standard_D2s_v3)"
}

variable "admin_username" {
  type        = string
  description = "Administrator username for RDP access"
}

variable "admin_password" {
  type        = string
  sensitive   = true
  description = "Administrator password for RDP access"
}

variable "os_disk_size_gb" {
  type        = number
  description = "OS disk size in GB"
  default     = 128
}

variable "os_disk_type" {
  type        = string
  description = "OS disk storage account type (StandardSSD_LRS, Premium_LRS, etc.)"
}

variable "data_disk_size_gb" {
  type        = number
  description = "SQL data disk size in GB"
}

variable "data_disk_type" {
  type        = string
  description = "SQL data disk storage account type"
}

variable "log_disk_size_gb" {
  type        = number
  description = "SQL log disk size in GB"
}

variable "log_disk_type" {
  type        = string
  description = "SQL log disk storage account type"
}

variable "sql_image" {
  type = object({
    publisher = string
    offer     = string
    sku       = string
    version   = string
  })
  description = "SQL Server marketplace image reference"
}

variable "user_username" {
  type        = string
  description = "Additional RDP user username"
}

variable "user_password" {
  type        = string
  sensitive   = true
  description = "Additional RDP user password"
}

variable "vnet_address_space" {
  type        = string
  description = "Address space for the virtual network"
  default     = "10.0.0.0/16"
}

variable "subnet_address_prefix" {
  type        = string
  description = "Address prefix for the subnet"
  default     = "10.0.1.0/24"
}
