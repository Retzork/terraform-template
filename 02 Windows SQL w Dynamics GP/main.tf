# Shared Image Gallery - GP + SQL Image (from image subscription)
data "azurerm_shared_image" "gp_sql" {
  provider            = azurerm.image
  name                = var.image_name
  gallery_name        = var.image_gallery_name
  resource_group_name = var.image_resource_group
}

# Use latest or specific version
data "azurerm_shared_image_version" "gp_sql" {
  provider            = azurerm.image
  name                = var.image_version
  image_name          = var.image_name
  gallery_name        = var.image_gallery_name
  resource_group_name = var.image_resource_group
}

# Resource Group
resource "azurerm_resource_group" "gp_rg" {
  name     = var.resource_group_name
  location = var.location
}

# Virtual Network
resource "azurerm_virtual_network" "gp_vnet" {
  name                = "${var.vm_name}-vnet"
  address_space       = [var.vnet_address_space]
  location            = azurerm_resource_group.gp_rg.location
  resource_group_name = azurerm_resource_group.gp_rg.name
}

# Subnet
resource "azurerm_subnet" "gp_subnet" {
  name                 = "${var.vm_name}-subnet"
  resource_group_name  = azurerm_resource_group.gp_rg.name
  virtual_network_name = azurerm_virtual_network.gp_vnet.name
  address_prefixes     = [var.subnet_address_prefix]
}

# Public IP
resource "azurerm_public_ip" "gp_pip" {
  name                = "${var.vm_name}-pip"
  location            = azurerm_resource_group.gp_rg.location
  resource_group_name = azurerm_resource_group.gp_rg.name
  allocation_method   = "Static"
  sku                 = "Standard"
}

# NSG - Allow RDP from office IPs only
resource "azurerm_network_security_group" "gp_nsg" {
  name                = "${var.vm_name}-nsg"
  location            = azurerm_resource_group.gp_rg.location
  resource_group_name = azurerm_resource_group.gp_rg.name

  security_rule {
    name                       = "Allow-RDP-Office"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "3389"
    source_address_prefixes    = ["103.79.155.206", "103.154.140.246"]
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "Deny-RDP-All"
    priority                   = 200
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "3389"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

# NIC
resource "azurerm_network_interface" "gp_nic" {
  name                = "${var.vm_name}-nic"
  location            = azurerm_resource_group.gp_rg.location
  resource_group_name = azurerm_resource_group.gp_rg.name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.gp_subnet.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.gp_pip.id
  }
}

# Associate NSG to NIC
resource "azurerm_network_interface_security_group_association" "gp_nic_nsg" {
  network_interface_id      = azurerm_network_interface.gp_nic.id
  network_security_group_id = azurerm_network_security_group.gp_nsg.id
}

# GP + SQL VM (from Shared Image Gallery)
resource "azurerm_windows_virtual_machine" "gp_vm" {
  name                = var.vm_name
  resource_group_name = azurerm_resource_group.gp_rg.name
  location            = azurerm_resource_group.gp_rg.location
  size                = var.vm_size
  admin_username      = var.admin_username
  admin_password      = var.admin_password

  network_interface_ids = [
    azurerm_network_interface.gp_nic.id,
  ]

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = var.os_disk_type
    disk_size_gb         = var.os_disk_size_gb
  }

  source_image_id = data.azurerm_shared_image_version.gp_sql.id

  # Required for Gen2 Trusted Launch images
  secure_boot_enabled = true
  vtpm_enabled        = true
}

# SQL Data Disk (custom size - separate from image disks)
resource "azurerm_managed_disk" "sql_data_disk" {
  name                 = "${var.vm_name}-data-disk"
  location             = azurerm_resource_group.gp_rg.location
  resource_group_name  = azurerm_resource_group.gp_rg.name
  storage_account_type = var.data_disk_type
  create_option        = "Empty"
  disk_size_gb         = var.data_disk_size_gb
}

resource "azurerm_virtual_machine_data_disk_attachment" "sql_data_disk_attach" {
  managed_disk_id    = azurerm_managed_disk.sql_data_disk.id
  virtual_machine_id = azurerm_windows_virtual_machine.gp_vm.id
  lun                = 2
  caching            = "ReadOnly"
}

# SQL Log Disk (custom size - separate from image disks)
resource "azurerm_managed_disk" "sql_log_disk" {
  name                 = "${var.vm_name}-log-disk"
  location             = azurerm_resource_group.gp_rg.location
  resource_group_name  = azurerm_resource_group.gp_rg.name
  storage_account_type = var.log_disk_type
  create_option        = "Empty"
  disk_size_gb         = var.log_disk_size_gb
}

resource "azurerm_virtual_machine_data_disk_attachment" "sql_log_disk_attach" {
  managed_disk_id    = azurerm_managed_disk.sql_log_disk.id
  virtual_machine_id = azurerm_windows_virtual_machine.gp_vm.id
  lun                = 3
  caching            = "None"
}

# Post-deploy script: Create user, enable mixed mode, configure SQL, setup ODBC DSN
resource "azurerm_virtual_machine_extension" "gp_setup" {
  name                 = "gp-post-deploy"
  virtual_machine_id   = azurerm_windows_virtual_machine.gp_vm.id
  publisher            = "Microsoft.Compute"
  type                 = "CustomScriptExtension"
  type_handler_version = "1.10"

  protected_settings = jsonencode({
    commandToExecute = "powershell -ExecutionPolicy Unrestricted -EncodedCommand ${textencodebase64(templatefile("${path.module}/scripts/post-deploy.ps1", {
      admin_password       = var.admin_password
      user_username        = var.user_username
      user_password        = var.user_password
      sql_data_drive       = var.sql_data_drive_letter
      sql_log_drive        = var.sql_log_drive_letter
      dsn_name             = var.gp_dsn_name
    }), "UTF-16LE")}"
  })

  depends_on = [
    azurerm_virtual_machine_data_disk_attachment.sql_data_disk_attach,
    azurerm_virtual_machine_data_disk_attachment.sql_log_disk_attach,
  ]
}
