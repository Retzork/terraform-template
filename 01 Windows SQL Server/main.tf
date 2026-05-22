# Resource Group
resource "azurerm_resource_group" "sql_rg" {
  name     = var.resource_group_name
  location = var.location
}

# Virtual Network
resource "azurerm_virtual_network" "sql_vnet" {
  name                = "${var.vm_name}-vnet"
  address_space       = [var.vnet_address_space]
  location            = azurerm_resource_group.sql_rg.location
  resource_group_name = azurerm_resource_group.sql_rg.name
}

# Subnet
resource "azurerm_subnet" "sql_subnet" {
  name                 = "${var.vm_name}-subnet"
  resource_group_name  = azurerm_resource_group.sql_rg.name
  virtual_network_name = azurerm_virtual_network.sql_vnet.name
  address_prefixes     = [var.subnet_address_prefix]
}

# Public IP for RDP access
resource "azurerm_public_ip" "sql_pip" {
  name                = "${var.vm_name}-pip"
  location            = azurerm_resource_group.sql_rg.location
  resource_group_name = azurerm_resource_group.sql_rg.name
  allocation_method   = "Static"
  sku                 = "Standard"
}

# NSG - Allow RDP from office IPs only
resource "azurerm_network_security_group" "sql_nsg" {
  name                = "${var.vm_name}-nsg"
  location            = azurerm_resource_group.sql_rg.location
  resource_group_name = azurerm_resource_group.sql_rg.name

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
resource "azurerm_network_interface" "sql_nic" {
  name                = "${var.vm_name}-nic"
  location            = azurerm_resource_group.sql_rg.location
  resource_group_name = azurerm_resource_group.sql_rg.name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.sql_subnet.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.sql_pip.id
  }
}

# Associate NSG to NIC
resource "azurerm_network_interface_security_group_association" "sql_nic_nsg" {
  network_interface_id      = azurerm_network_interface.sql_nic.id
  network_security_group_id = azurerm_network_security_group.sql_nsg.id
}

# SQL Server VM
resource "azurerm_windows_virtual_machine" "sql_vm" {
  name                = var.vm_name
  resource_group_name = azurerm_resource_group.sql_rg.name
  location            = azurerm_resource_group.sql_rg.location
  size                = var.vm_size
  admin_username      = var.admin_username
  admin_password      = var.admin_password

  network_interface_ids = [
    azurerm_network_interface.sql_nic.id,
  ]

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = var.os_disk_type
    disk_size_gb         = var.os_disk_size_gb
  }

  source_image_reference {
    publisher = var.sql_image.publisher
    offer     = var.sql_image.offer
    sku       = var.sql_image.sku
    version   = var.sql_image.version
  }
}

# Create additional RDP user via CustomScriptExtension
resource "azurerm_virtual_machine_extension" "create_user" {
  name                 = "create-rdp-user"
  virtual_machine_id   = azurerm_windows_virtual_machine.sql_vm.id
  publisher            = "Microsoft.Compute"
  type                 = "CustomScriptExtension"
  type_handler_version = "1.10"

  protected_settings = jsonencode({
    commandToExecute = "powershell -ExecutionPolicy Unrestricted -Command \"net user '${var.user_username}' '${var.user_password}' /add /y; net localgroup 'Remote Desktop Users' '${var.user_username}' /add; net localgroup 'Administrators' '${var.user_username}' /add\""
  })
}

# Data Disk (SQL Data)
resource "azurerm_managed_disk" "sql_data_disk" {
  name                 = "${var.vm_name}-data-disk"
  location             = azurerm_resource_group.sql_rg.location
  resource_group_name  = azurerm_resource_group.sql_rg.name
  storage_account_type = var.data_disk_type
  create_option        = "Empty"
  disk_size_gb         = var.data_disk_size_gb
}

resource "azurerm_virtual_machine_data_disk_attachment" "sql_data_disk_attach" {
  managed_disk_id    = azurerm_managed_disk.sql_data_disk.id
  virtual_machine_id = azurerm_windows_virtual_machine.sql_vm.id
  lun                = 0
  caching            = "ReadOnly"
}

# Log Disk (SQL Log)
resource "azurerm_managed_disk" "sql_log_disk" {
  name                 = "${var.vm_name}-log-disk"
  location             = azurerm_resource_group.sql_rg.location
  resource_group_name  = azurerm_resource_group.sql_rg.name
  storage_account_type = var.log_disk_type
  create_option        = "Empty"
  disk_size_gb         = var.log_disk_size_gb
}

resource "azurerm_virtual_machine_data_disk_attachment" "sql_log_disk_attach" {
  managed_disk_id    = azurerm_managed_disk.sql_log_disk.id
  virtual_machine_id = azurerm_windows_virtual_machine.sql_vm.id
  lun                = 1
  caching            = "None"
}
