# 01 Windows SQL Server

A simple, configurable Windows SQL Server VM template for Azure.

## What it deploys

- Resource Group
- VNet + Subnet
- Public IP (Static) + NSG with RDP allowed
- Windows VM with SQL Server marketplace image
- 128 GB Standard SSD OS disk
- 256 GB Standard SSD data disk (LUN 0)
- 256 GB Standard SSD log disk (LUN 1)

## Configuration

All key settings are in `terraform.tfvars`:

| Variable | Description |
|----------|-------------|
| `resource_group_name` | Name of the resource group |
| `location` | Azure region |
| `vm_name` | VM name |
| `vm_size` | VM size (e.g. Standard_D2s_v3) |
| `admin_username` | RDP username |
| `admin_password` | RDP password |
| `os_disk_size_gb` | OS disk size |
| `os_disk_type` | OS disk type |
| `data_disk_size_gb` | SQL data disk size |
| `data_disk_type` | SQL data disk type |
| `log_disk_size_gb` | SQL log disk size |
| `log_disk_type` | SQL log disk type |
| `sql_image` | Marketplace image (publisher/offer/sku/version) |

## Usage

```bash
terraform init
terraform plan
terraform apply
```

After deployment, RDP into the VM using the public IP from the output.
