# Artemis KG Embeddings

Containerized Nextflow pipeline for generating knowledge graph embeddings and link predictions using PyKEEN for multiple biomedical KGs (Hetionet, BioKG, OpenBioLink, PrimeKG).

## Repository Structure

- Workflow: `main.nf` (process `embedding`)
- Python script: `bin/generate_embeddings.py` (embedding generation with data leakage prevention)
- Global config: `nextflow.config`
- Per-model hyperparameters: `conf/<model>/<dataset>.yaml` (e.g. `conf/RotatE/hetionet.yaml`)
- Container build: `Dockerfile`, `requirements.txt`
- Deployment pipeline: `.github/workflows/docker-deploy.yml`
- Terraform (public ECR): `terraform/main.tf`, `terraform/providers.tf`, `terraform/backend.hcl`
- Tests: `tests/test_filtering.py`, `tests/test_removed_output.py`
- Ignore rules: `.gitignore`
- License: `LICENSE`

## Pipeline Overview

The Nextflow process `embedding` loads a selected dataset via PyKEEN, merges training/validation/testing triples, and runs `pipeline()` with hyperparameters from a YAML config in `conf/<model>/<dataset>.yaml`. Results are saved to `<save.path>/<model_name>/`.

**Data Leakage Prevention:** The pipeline includes optional filtering to remove drug-gene interactions for clinical target genes. This prevents the embedding model from encoding known drug-target relationships that would leak into downstream druggability prediction tasks. When `clinical_targets` is specified, the pipeline:
- Loads clinical target gene symbols from CSV files
- Maps gene symbols to knowledge graph entity IDs
- Identifies drug/compound entities in the KG
- Removes all drug-gene interaction triples for clinical targets
- Generates detailed filtering statistics

This ensures that embeddings learn biological features of druggable genes rather than simply encoding "this gene is already targeted by drugs."

### Required YAML Config Keys

```yaml
save:
  path: hetionet
model:
  name: RotatE
  embedding_dim: 512
seed: 42
train:
  loss_function: MarginRankingLoss
  num_epoch: 500
  num_negative: 41
  create_inverse: False
optimizer:
  class: Adagrad
  lr: 0.03
```

### Parameters (Nextflow)

- `params.dataset` (one of: hetionet, biokg, openbiolink, primekg; default: null = all datasets)
- `params.model` (one of: RotatE, TransE, ComplEx, DistMult, all; default: all)
- `params.clinical_targets` (S3 directory containing clinical target CSV files)
- `params.outdir` (publish directory / S3 prefix)
- `params.skip_existing` (boolean; default: true — skip dataset/model combos that already have output in `outdir`)
- `params.test_mode` (boolean; default: false — when true, runs only hetionet + RotatE for quick validation)
- `params.max_time` (wall-time hint)

The YAML config is auto-resolved from `conf/<model>/<dataset>.yaml`.

## Running the Workflow

Run all models on all KGs in parallel (16 jobs):
```bash
nextflow run main.nf
```

Run all models for a single KG (4 jobs):
```bash
nextflow run main.nf --dataset hetionet
```

Run a single model on a single KG:
```bash
nextflow run main.nf --dataset hetionet --model RotatE
```

Run a single model on all KGs (4 jobs):
```bash
nextflow run main.nf --model TransE
```

Override output dir:
```bash
nextflow run main.nf --dataset openbiolink --outdir s3://bucket/path/
```

Quick validation run (hetionet + RotatE only):
```bash
nextflow run main.nf --test_mode
```

Force re-run even if output already exists:
```bash
nextflow run main.nf --skip_existing false
```

By default (`skip_existing = true`), the pipeline checks S3 for existing output and skips any dataset/model combination that already has results in `outdir`.

## Embedding Models

The pipeline supports multiple knowledge graph embedding algorithms via PyKEEN:

| Model | Description |
|---|---|
| **RotatE** | Rotation-based model; captures symmetry, antisymmetry, inversion, and composition patterns |
| **TransE** | Translation-based model; effective for antisymmetric and inversion relations |
| **ComplEx** | Complex-valued bilinear model; handles symmetric and antisymmetric relations |
| **DistMult** | Real-valued bilinear model; suited for symmetric relations |

By default, all four models run in parallel for every dataset. To narrow to a specific model, pass `--model`:

```bash
nextflow run main.nf --dataset hetionet --model ComplEx
```

Hyperparameters for Hetionet and BioKG are sourced from Table 5 of [Bonner et al. (2022)](https://www.sciencedirect.com/science/article/pii/S2667318522000071). For OpenBioLink and PrimeKG (not covered in the study), hyperparameters are adapted from the closest-scale KG in Table 5.

Results are saved to a subdirectory named after the model (e.g. `save_path/ComplEx/`) to keep outputs from different models separate.

### Hyperparameter Selection

Embeddings are generated using four KGE algorithms — RotatE [1], TransE [2], ComplEx [3] and DistMult [4] — implemented in the PyKEEN framework [5]. All models are trained using the sLCWA (stochastic local closed-world assumption) training loop with the Margin Ranking Loss objective and the Adagrad optimiser, following the training setup found to perform best across biomedical KGs by Bonner et al. [6].

Model-specific hyperparameters (embedding dimension, learning rate, number of training epochs and number of negative samples) for Hetionet and BioKG are taken directly from the best-performing configurations reported in Table 5 of Bonner et al. [6], which were identified through a hyperparameter optimisation study spanning 100 trials per model-dataset combination. For OpenBioLink and PrimeKG, which were not included in that study, hyperparameters are adapted from the most structurally similar KG: OpenBioLink uses Hetionet parameters (comparable entity count) and PrimeKG uses BioKG parameters (larger, denser graph), with the number of epochs reduced to 150 for PrimeKG to account for its substantially larger triple count (~8M vs ~2M).

#### Hetionet

| Parameter | RotatE | TransE | ComplEx | DistMult |
|---|---|---|---|---|
| Embedding dimension | 512 | 304 | 272 | 80 |
| Learning rate | 0.03 | 0.02 | 0.03 | 0.02 |
| Epochs | 500 | 500 | 700 | 400 |
| Negative samples | 41 | 61 | 91 | 41 |
| Source | Table 5 [6] | Table 5 [6] | Table 5 [6] | Table 5 [6] |

#### BioKG

| Parameter | RotatE | TransE | ComplEx | DistMult |
|---|---|---|---|---|
| Embedding dimension | 448 | 448 | 464 | 480 |
| Learning rate | 0.06 | 0.1 | 0.09 | 0.05 |
| Epochs | 900 | 600 | 600 | 100 |
| Negative samples | 31 | 91 | 91 | 71 |
| Source | Table 5 [6] | Table 5 [6] | Table 5 [6] | Table 5 [6] |

#### OpenBioLink

| Parameter | RotatE | TransE | ComplEx | DistMult |
|---|---|---|---|---|
| Embedding dimension | 512 | 304 | 272 | 80 |
| Learning rate | 0.03 | 0.02 | 0.03 | 0.02 |
| Epochs | 500 | 500 | 700 | 400 |
| Negative samples | 41 | 61 | 91 | 41 |
| Source | Adapted from Hetionet [6] | Adapted from Hetionet [6] | Adapted from Hetionet [6] | Adapted from Hetionet [6] |

#### PrimeKG

| Parameter | RotatE | TransE | ComplEx | DistMult |
|---|---|---|---|---|
| Embedding dimension | 448 | 448 | 464 | 480 |
| Learning rate | 0.06 | 0.1 | 0.09 | 0.05 |
| Epochs | 150 | 150 | 150 | 150 |
| Negative samples | 31 | 91 | 91 | 71 |
| Source | Adapted from BioKG [6] | Adapted from BioKG [6] | Adapted from BioKG [6] | Adapted from BioKG [6] |

All models use: Optimiser = Adagrad, Loss = Margin Ranking Loss, Inverse triples = False, Random seed = 42.

#### References

- [1] Sun, Z. et al. RotatE: Knowledge graph embedding by relational rotation in complex space. ICLR (2019).
- [2] Bordes, A. et al. Translating embeddings for modeling multi-relational data. NeurIPS (2013).
- [3] Trouillon, T. et al. Complex embeddings for simple link prediction. ICML (2016).
- [4] Yang, B. et al. Embedding entities and relations for learning and inference in knowledge bases. ICLR (2015).
- [5] Ali, M. et al. PyKEEN 1.0: A Python library for training and evaluating knowledge graph embeddings. JMLR 22(82):1–6 (2021).
- [6] Bonner, S. et al. Understanding the performance of knowledge graph embeddings in drug discovery. Artificial Intelligence in the Life Sciences 2, 100036 (2022).

## Clinical Targets Filtering

To prevent data leakage in druggability prediction tasks, the pipeline can filter out drug-gene interactions for known clinical target genes.

### Input Format

The `clinical_targets` parameter should point to an S3 directory containing CSV files with clinical target genes. Each CSV should have gene symbols in the first column:

```csv
Target Gene,phase_0,phase_1,phase_2,phase_3,phase_4,Phase Score,approved,Clinical Score
PDCD1,0,1,21,100,0,343.0,False,343.0
EGFR,0,0,2,81,0,247.0,False,247.0
ESR1,0,1,7,73,71,234.0,True,254.0
```

The pipeline will:
1. Load all gene symbols from CSV files in the directory
2. Map gene symbols to KG entity IDs (handling different naming conventions per KG)
3. Identify drug/compound entities in the KG
4. Remove triples where a clinical target gene interacts with a drug/compound
5. Generate `filtering_stats.json` with detailed statistics

### Output

The filtering process outputs `filtering_stats.json` containing:
- Number of clinical genes found in the KG
- Number of drug entities identified
- Filtering statistics per split (training/testing/validation):
  - Original triple count
  - Filtered triple count
  - Remaining triple count
  - Percentage removed

### Disabling Filtering

To run without filtering (for comparison or when clinical targets are not applicable), set `clinical_targets` to `null` or omit it:

```bash
nextflow run main.nf --dataset hetionet --clinical_targets null
```

## Tests

The `tests/` directory contains integration tests for the filtering logic:

- `test_filtering.py` — End-to-end test of all non-GPU steps: loading clinical targets from S3, mapping gene symbols to KG entities, identifying drug entities, filtering drug-gene triples, and verifying TriplesFactory creation across all four KGs.
- `test_removed_output.py` — Verifies that removed triples are correctly captured and saved.

Run tests (requires AWS credentials for S3 access):
```bash
python tests/test_filtering.py
python tests/test_removed_output.py
```

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

Hyperparameter YAML configs are stored in `conf/<model>/<dataset>.yaml`:

```
conf/
  RotatE/     # Rotation-based (default)
  TransE/     # Translation-based
  ComplEx/    # Complex-valued bilinear
  DistMult/   # Real-valued bilinear
    hetionet.yaml
    biokg.yaml
    openbiolink.yaml
    primekg.yaml
```

Per-dataset resource allocation (cpus, memory) is handled dynamically in the process definition in `main.nf`.

Global defaults in `nextflow.config`:
- `process.container` points to `public.ecr.aws/alethiotx/artemis-kgs-embeddings:latest`
- `process.containerOptions` enables `--gpus all`

## CUDA Check

The script writes `cuda_version.txt` after allocating a CUDA tensor to assert GPU availability.

## Outputs

`pipeline_result.save_to_directory(<save_path>/<model_name>/)` produces:
- Model artifacts
- Embeddings
- Evaluation metrics

Directory path is controlled by `save.path` in YAML, with the model name appended as a subdirectory.

## Troubleshooting

- Wrong dataset name: ensure it is one of hetionet, biokg, openbiolink, primekg.
- Missing GPU: container must run with `--gpus all`.
- Config path issues: verify S3 permissions and YAML keys.

## License

MIT License in `LICENSE`.

## Minimal End-to-End Example

```bash
nextflow run main.nf
```

Runs all 4 models on all 4 KGs (16 parallel jobs).

## Referenced Files

`Dockerfile`  
`requirements.txt`  
`main.nf`  
`nextflow.config`  
`conf/RotatE/*.yaml`  
`conf/TransE/*.yaml`  
`conf/ComplEx/*.yaml`  
`conf/DistMult/*.yaml`  
`.github/workflows/docker-deploy.yml`  
`terraform/main.tf`  
`terraform/providers.tf`  
`terraform/backend.hcl`  
`.gitignore`  
`LICENSE`

## Acknowledgements

- Public knowledge graph providers (Hetionet, BioKG, OpenBioLink, PrimeKG)
- PyKEEN, scikit-learn, and Nextflow communities
- Portions of this codebase were assisted using GitHub Copilot (Claude Sonnet 4.5) for code generation, refactoring, cleaning and documentation. The authors reviewed, modified, and validated all AI-assisted code. Responsibility for the correctness, performance, and reproducibility of the code rests entirely with the authors. No AI tools were used to generate scientific conclusions or interpretations in this study.