# VPC Module

Creates a complete VPC with public/private subnets, NAT gateway, internet gateway, route tables, flow logs, and a private Route 53 zone.

## Usage

```hcl
module "vpc" {
  source = "./modules/vpc"

  name                = "observal-prod"
  vpc_cidr            = "10.42.0.0/16"
  azs                 = ["us-east-1a", "us-east-1b"]
  public_subnet_cidrs = ["10.42.0.0/24", "10.42.1.0/24"]
  private_subnet_cidrs = ["10.42.10.0/24", "10.42.11.0/24"]
  internal_dns_zone   = "observal.internal"
  log_retention_days  = 30
  enable_flow_logs    = true

  tags = {
    Environment = "prod"
    Project     = "observal"
  }
}
