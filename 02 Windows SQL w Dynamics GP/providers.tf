terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }

  backend "azurerm" {}
}

provider "azurerm" {
  subscription_id = var.subscription_id
  features {}
}

# Aliased provider for reading image from a different subscription
provider "azurerm" {
  alias           = "image"
  subscription_id = var.image_subscription_id
  features {}
}
