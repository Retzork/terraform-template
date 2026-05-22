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
  description = "Name of the GP + SQL virtual machine"
}

variable "vm_size" {
  type        = string
  description = "Virtual Machine size (e.g. Standard_D4s_v3)"
}

variable "admin_username" {
  type        = string
  description = "Administrator username for RDP access"
}

variable "admin_password" {
  type        = string
  sensitive   = true
  description = "Administrator password for RDP and SQL SA access"
}

# Additional RDP User
variable "user_username" {
  type        = string
  description = "Additional RDP user username"
}

variable "user_password" {
  type        = string
  sensitive   = true
  description = "Additional RDP user password"
}

# Image Reference
variable "image_subscription_id" {
  type        = string
  description = "Azure subscription ID where the Shared Image Gallery resides"
}

variable "image_resource_group" {
  type        = string
  description = "Resource group containing the Shared Image Gallery"
  default     = "SHAREDIMAGESRG"
}

variable "image_gallery_name" {
  type        = string
  description = "Shared Image Gallery name"
  default     = "GPImageGallery"
}

variable "image_name" {
  type        = string
  description = "Image definition name in the gallery"
}

variable "image_version" {
  type        = string
  description = "Image version (e.g. 1.0.0)"
  default     = "latest"
}

# OS Disk
variable "os_disk_size_gb" {
  type        = number
  description = "OS disk size in GB (must be >= image OS disk size)"
  default     = 128
}

variable "os_disk_type" {
  type        = string
  description = "OS disk storage type (StandardSSD_LRS, Premium_LRS, Standard_LRS)"
  default     = "StandardSSD_LRS"
}

# SQL Data Disk
variable "data_disk_size_gb" {
  type        = number
  description = "SQL data disk size in GB"
}

variable "data_disk_type" {
  type        = string
  description = "SQL data disk storage type"
  default     = "StandardSSD_LRS"
}

# SQL Log Disk
variable "log_disk_size_gb" {
  type        = number
  description = "SQL log disk size in GB"
}

variable "log_disk_type" {
  type        = string
  description = "SQL log disk storage type"
  default     = "StandardSSD_LRS"
}

# Network
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

# GP ODBC DSN
variable "gp_dsn_name" {
  type        = string
  description = "ODBC DSN name for Dynamics GP"
  default     = "DynamicsGP"
}

# SQL Data/Log paths on the attached disks
variable "sql_data_drive_letter" {
  type        = string
  description = "Drive letter for SQL data disk"
  default     = "F"
}

variable "sql_log_drive_letter" {
  type        = string
  description = "Drive letter for SQL log disk"
  default     = "G"
}
