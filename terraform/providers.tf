terraform {
  required_version = ">=1.6.5"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      version = ">=5.26.0"
    }
  }
}

# ECR Public is only in us-east-1
provider "aws" {
  alias                       = "us_east_1"
  region                      = "us-east-1"
  skip_metadata_api_check     = true
  skip_region_validation      = true
  skip_credentials_validation = true
}