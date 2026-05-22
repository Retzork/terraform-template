output "public_ip_address" {
  value       = azurerm_public_ip.gp_pip.ip_address
  description = "Public IP address for RDP access"
}

output "vm_name" {
  value       = azurerm_windows_virtual_machine.gp_vm.name
  description = "Name of the GP + SQL VM"
}

output "rdp_username" {
  value       = var.user_username
  description = "RDP username"
}
