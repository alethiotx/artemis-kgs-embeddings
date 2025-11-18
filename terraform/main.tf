terraform {
  // Backend moved to terraform/backend.hcl (untracked). Initialize with:
  // terraform init -reconfigure -backend-config=backend.hcl
  backend "s3" {}  // required to use -backend-config
}

# Public ECR repository (ECR Public)
resource "aws_ecrpublic_repository" "this" {
  provider = aws.us_east_1
  repository_name = "artemis-kgs-embeddings"

  catalog_data {
    about_text = "Public image for KG embeddings and link prediction using PyKEEN."
  }
}

# Allow anonymous pull
resource "aws_ecrpublic_repository_policy" "this" {
  provider        = aws.us_east_1
  repository_name = aws_ecrpublic_repository.this.repository_name

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Sid       = "AllowPublicPull"
      Effect    = "Allow"
      Principal = "*"
      Action = [
        "ecr-public:BatchCheckLayerAvailability",
        "ecr-public:BatchGetImage",
        "ecr-public:GetDownloadUrlForLayer"
      ]
    }]
  })
}

output "public_image_uri_latest" {
  value = "${aws_ecrpublic_repository.this.repository_uri}:latest"
}
