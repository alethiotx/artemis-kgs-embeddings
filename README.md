# Artemis KG Embeddings

Containerized Nextflow pipeline for generating knowledge graph embeddings and link predictions using PyKEEN for multiple biomedical KGs (Hetionet, BioKG, OpenBioLink, PrimeKG).

## Repository Structure

- Workflow: `main.nf` (process `embedding`)
- Global config: `nextflow.config`
- Per-dataset profiles: `conf/hetionet.config`, `conf/biokg.config`, `conf/openbiolink.config`, `conf/primekg.config`
- Container build: `Dockerfile`, `requirements.txt`
- Deployment pipeline: `.github/workflows/docker-deploy.yml`
- Terraform (public ECR): `terraform/main.tf`, `terraform/providers.tf`, `terraform/backend.hcl`
- Ignore rules: `.gitignore`
- License: `LICENSE`

## Pipeline Overview

The Nextflow process `embedding` loads a selected dataset via PyKEEN, merges training/validation/testing triples, and runs `pipeline()` with user-supplied hyperparameters from a remote YAML config. Results are saved to `config["save"]["path"]`.

### Required YAML Config Keys

```yaml
save:
  path: /output/dir
model:
  name: TransE
  embedding_dim: 256
seed: 42
train:
  num_epoch: 50
  num_negative: 32
optimizer:
  class: Adam
  lr: 0.0005
```

### Parameters (Nextflow)

- `params.dataset` (one of: hetionet, biokg, openbiolink, primekg)
- `params.config` (S3 or local path to YAML)
- `params.outdir` (publish directory / S3 prefix)
- `params.max_time` (wall-time hint)

Profiles supply dataset + config path (see `conf/*.config` files).

## Running the Workflow

Use a profile (recommended):
```bash
nextflow run main.nf -profile hetionet
```

Override output dir:
```bash
nextflow run main.nf -profile openbiolink --outdir s3://bucket/path/
```

Direct parameter usage (without profile):
```bash
nextflow run main.nf --dataset hetionet --config s3://bucket/configs/hetionet.yaml
```

GPU container is defined in `nextflow.config` (uses image pushed to public ECR).

## Docker Image

Build locally:
```bash
docker build -t artemis-kgs-embeddings:local -f Dockerfile .
```

The CI workflow `.github/workflows/docker-deploy.yml` auto-tags images with either:
- Git tag (without leading `v`)
- Commit short SHA

Public ECR repository name is created via Terraform.

## Terraform (Public ECR)

Initialize (adjust bucket/table in `terraform/backend.hcl`):
```bash
cd terraform
terraform init -reconfigure -backend-config=backend.hcl
terraform apply
```

Outputs:
- `public_image_uri_latest`

Resources:
- Repository: `terraform/main.tf`
- Provider setup: `terraform/providers.tf`

## Configuration Files

Each profile file (e.g. `conf/openbiolink.config`) sets:
- `params.dataset`
- `params.config` (S3 path to YAML)
- Optional resource overrides (cpus, memory)

Global defaults in `nextflow.config`:
- `process.container` points to `public.ecr.aws/alethiotx/artemis-kgs-embeddings:latest`
- `process.containerOptions` enables `--gpus all`

## CUDA Check

The script writes `cuda_version.txt` after allocating a CUDA tensor to assert GPU availability.

## Outputs

`pipeline_result.save_to_directory(config["save"]["path"])` produces:
- Model artifacts
- Embeddings
- Evaluation metrics

Directory path is controlled by `save.path` in YAML.

## Troubleshooting

- Wrong dataset name: ensure it matches profile.
- Missing GPU: container must run with `--gpus all`.
- Config path issues: verify S3 permissions and YAML keys.

## License

MIT License in `LICENSE`.

## Minimal End-to-End Example

```bash
nextflow run main.nf -profile hetionet
```

## Referenced Files

`Dockerfile`  
`requirements.txt`  
`main.nf`  
`nextflow.config`  
`conf/hetionet.config`  
`conf/biokg.config`  
`conf/openbiolink.config`  
`conf/primekg.config`  
`.github/workflows/docker-deploy.yml`  
`terraform/main.tf`  
`terraform/providers.tf`  
`terraform/backend.hcl`  
`.gitignore`  
`LICENSE`