#!/usr/bin/env python3

from pykeen.pipeline import pipeline
from pykeen.datasets import Hetionet, BioKG, OpenBioLink, PrimeKG
from pykeen.triples import TriplesFactory
import numpy as np
import sys
import yaml
import torch
import pandas as pd
import s3fs
import json
from typing import Set, Dict, List, Tuple
import os

SUPPORTED_MODELS = ['RotatE', 'TransE', 'ComplEx', 'DistMult']

def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    return config

def load_clinical_targets(s3_dir: str) -> Set[str]:
    """Load all clinical target gene symbols from S3 CSV files"""
    if not s3_dir or s3_dir == 'NONE':
        return set()
    
    print(f"Loading clinical targets from {s3_dir}")
    fs = s3fs.S3FileSystem(anon=False)
    
    # List all CSV files in the directory
    files = fs.ls(s3_dir)
    csv_files = [f for f in files if f.endswith('.csv')]
    
    all_genes = set()
    for csv_file in csv_files:
        print(f"  Reading {csv_file}")
        with fs.open(csv_file, 'r') as f:
            df = pd.read_csv(f)
            # First column should be gene symbols
            genes = df.iloc[:, 0].dropna().astype(str).tolist()
            all_genes.update(genes)
            print(f"    Found {len(genes)} genes")
    
    print(f"Total unique clinical target genes: {len(all_genes)}")
    return all_genes

def _load_ncbi_gene_symbol_map() -> Dict[str, str]:
    """Download NCBI gene_info and build gene symbol -> Entrez ID mapping for human genes."""
    url = "https://ftp.ncbi.nlm.nih.gov/gene/DATA/GENE_INFO/Mammalia/Homo_sapiens.gene_info.gz"
    print(f"  Downloading NCBI gene_info from {url}")
    gene_info = pd.read_csv(url, sep='\t', usecols=['GeneID', 'Symbol', 'Synonyms'])
    gene_info['GeneID'] = gene_info['GeneID'].astype(str)
    
    # Primary symbols
    symbol_to_entrez = dict(zip(gene_info['Symbol'], gene_info['GeneID']))
    
    # Also index synonyms (only where not already mapped by primary symbol)
    synonym_rows = gene_info[gene_info['Synonyms'] != '-']
    for entrez_id, synonyms in zip(synonym_rows['GeneID'], synonym_rows['Synonyms']):
        for syn in str(synonyms).split('|'):
            if syn not in symbol_to_entrez:
                symbol_to_entrez[syn] = entrez_id
    
    print(f"  Loaded {len(gene_info)} genes ({len(symbol_to_entrez)} symbols incl. synonyms)")
    return symbol_to_entrez

def _load_uniprot_gene_symbol_map() -> Dict[str, List[str]]:
    """Download UniProt reviewed human entries and build gene symbol -> accession mapping."""
    url = (
        "https://rest.uniprot.org/uniprotkb/stream"
        "?query=(organism_id:9606)+AND+(reviewed:true)"
        "&format=tsv&fields=accession,gene_primary"
    )
    print(f"  Downloading UniProt ID mapping")
    uniprot_df = pd.read_csv(url, sep='\t').dropna()
    
    symbol_to_accessions: Dict[str, List[str]] = {}
    for gene_name, accession in zip(uniprot_df['Gene Names (primary)'], uniprot_df['Entry']):
        symbol_to_accessions.setdefault(str(gene_name), []).append(str(accession))
    
    print(f"  Loaded {len(symbol_to_accessions)} gene-to-UniProt mappings")
    return symbol_to_accessions

def map_gene_symbols_to_entities(gene_symbols: Set[str], entity_to_id: Dict[str, int], 
                                 dataset_name: str) -> Set[str]:
    """Map gene symbols to KG entity label strings.
    
    Entity naming per KG:
      - Hetionet:    Gene::<entrez_id>       (e.g. Gene::1956)
      - BioKG:       <uniprot_accession>     (e.g. P00533)
      - OpenBioLink: NCBIGENE:<entrez_id>    (e.g. NCBIGENE:1956)
      - PrimeKG:     <gene_symbol>           (e.g. EGFR)
    
    Uses NCBI gene_info (Hetionet/OpenBioLink) or UniProt ID mapping (BioKG)
    to convert gene symbols to the identifiers used by each KG.
    
    Returns set of KG entity label strings for the matched genes.
    """
    if not gene_symbols:
        return set()
    
    print(f"\nMapping {len(gene_symbols)} gene symbols to {dataset_name} entities...")
    
    matched_entities = set()
    matched_genes = set()

    if dataset_name == 'primekg':
        # PrimeKG uses plain gene symbols - direct match
        for gene in gene_symbols:
            if gene in entity_to_id:
                matched_entities.add(gene)
                matched_genes.add(gene)
    
    elif dataset_name in ('hetionet', 'openbiolink'):
        # Both use Entrez Gene IDs - convert via NCBI gene_info
        symbol_to_entrez = _load_ncbi_gene_symbol_map()
        
        resolved = 0
        for gene in gene_symbols:
            entrez_id = symbol_to_entrez.get(gene)
            if entrez_id is None:
                continue
            resolved += 1
            
            if dataset_name == 'hetionet':
                entity_str = f"Gene::{entrez_id}"
            else:  # openbiolink
                entity_str = f"NCBIGENE:{entrez_id}"
            
            if entity_str in entity_to_id:
                matched_entities.add(entity_str)
                matched_genes.add(gene)
        
        print(f"  Resolved {resolved} / {len(gene_symbols)} symbols to Entrez IDs")
    
    elif dataset_name == 'biokg':
        # BioKG uses UniProt accessions for proteins
        symbol_to_accessions = _load_uniprot_gene_symbol_map()
        
        resolved = 0
        for gene in gene_symbols:
            accessions = symbol_to_accessions.get(gene, [])
            if not accessions:
                continue
            resolved += 1
            
            for uid in accessions:
                if uid in entity_to_id:
                    matched_entities.add(uid)
                    matched_genes.add(gene)
                    break
        
        print(f"  Resolved {resolved} / {len(gene_symbols)} symbols to UniProt IDs")
    
    print(f"  Mapped {len(matched_genes)} / {len(gene_symbols)} genes to {len(matched_entities)} KG entities")
    if len(matched_genes) < len(gene_symbols):
        unmapped = gene_symbols - matched_genes
        print(f"  WARNING: {len(unmapped)} genes not found in KG: {sorted(unmapped)[:20]}")
    
    return matched_entities

def identify_drug_entities(entity_to_id: Dict[str, int], dataset_name: str) -> Set[str]:
    """Identify drug/compound entity label strings in the KG.
    
    Drug entity naming per KG:
      - Hetionet:    Compound::<drugbank_id>          (e.g. Compound::DB00001)
      - BioKG:       <drugbank_id>                    (e.g. DB00001) - bare DrugBank IDs
      - OpenBioLink: PUBCHEM.COMPOUND:<pubchem_cid>   (e.g. PUBCHEM.COMPOUND:10240)
      - PrimeKG:     not identifiable by prefix - uses relation-based filtering instead
    
    Returns set of KG entity label strings for drug/compound entities.
    """
    print(f"\nIdentifying drug/compound entities in {dataset_name}...")
    
    drug_entities = set()
    
    if dataset_name == 'hetionet':
        for entity_str in entity_to_id:
            if entity_str.startswith('Compound::'):
                drug_entities.add(entity_str)
    
    elif dataset_name == 'biokg':
        for entity_str in entity_to_id:
            if entity_str.startswith('DB'):
                drug_entities.add(entity_str)
    
    elif dataset_name == 'openbiolink':
        for entity_str in entity_to_id:
            if entity_str.startswith('PUBCHEM.COMPOUND:'):
                drug_entities.add(entity_str)
    
    elif dataset_name == 'primekg':
        print("  PrimeKG uses plain drug names - will filter by drug_protein relation type instead")
    
    print(f"  Found {len(drug_entities)} drug/compound entities")
    return drug_entities

def filter_drug_gene_triples(triples: np.ndarray, gene_entities: Set[str], 
                             drug_entities: Set[str],
                             dataset_name: str = '',
                             relation_to_id: Dict[str, int] = None) -> Tuple[np.ndarray, np.ndarray, Dict]:
    """
    Filter out drug-gene interaction triples to prevent data leakage.
    
    Triples are labeled string arrays from PyKEEN (shape: [n, 3], columns: head, relation, tail).
    
    For Hetionet, BioKG, OpenBioLink: filters triples where one entity is a clinical gene
    and the other is a drug/compound.
    For PrimeKG: filters triples with drug-related relation types (drug_protein, drug_drug, 
    indication, contraindication, off-label use) that involve clinical target genes.
    
    Returns (filtered_triples, removed_triples, statistics).
    """
    if not gene_entities:
        return triples, np.empty((0, 3), dtype=triples.dtype), {'filtered': 0, 'kept': len(triples)}
    
    print(f"\nFiltering drug-gene triples...")
    print(f"  Clinical gene entities: {len(gene_entities)}")
    print(f"  Drug entities: {len(drug_entities)}")
    print(f"  Original triples: {len(triples)}")
    
    heads = triples[:, 0]
    relations = triples[:, 1]
    tails = triples[:, 2]
    
    if dataset_name == 'primekg':
        # PrimeKG: filter by relation type since drugs have no distinguishable prefix
        drug_relation_names = set()
        if relation_to_id is not None:
            for rel_name in relation_to_id:
                if 'drug' in rel_name.lower():
                    drug_relation_names.add(rel_name)
                    print(f"  Drug relation found: '{rel_name}'")
        
        # Use vectorized Python set lookups via list comprehension for speed on string arrays
        mask = np.array([
            rel in drug_relation_names and (h in gene_entities or t in gene_entities)
            for h, rel, t in zip(heads, relations, tails)
        ], dtype=bool)
        drug_gene_interactions = mask
    else:
        # Prefix-based approach for Hetionet, BioKG, OpenBioLink
        mask = np.array([
            (h in gene_entities and t in drug_entities) or (h in drug_entities and t in gene_entities)
            for h, t in zip(heads, tails)
        ], dtype=bool)
        drug_gene_interactions = mask
    
    removed_triples = triples[drug_gene_interactions]
    filtered_triples = triples[~drug_gene_interactions]
    
    stats = {
        'original': len(triples),
        'filtered': int(drug_gene_interactions.sum()),
        'kept': len(filtered_triples),
        'percent_removed': float(drug_gene_interactions.sum() / len(triples) * 100)
    }
    
    print(f"  Filtered: {stats['filtered']} triples ({stats['percent_removed']:.2f}%)")
    print(f"  Remaining: {stats['kept']} triples")
    
    return filtered_triples, removed_triples, stats

def main():
    if len(sys.argv) != 4:
        print("Usage: generate_embeddings.py <dataset> <config_path> <clinical_targets_dir>")
        sys.exit(1)
    
    dataset = sys.argv[1]
    config_path = sys.argv[2]
    clinical_targets_dir = sys.argv[3]

    config: dict = load_config(config_path)

    model_name = config["model"]["name"]

    # Validate model name
    if model_name not in SUPPORTED_MODELS:
        print(f"Model '{model_name}' is not supported. Supported models: {SUPPORTED_MODELS}")
        sys.exit(1)

    print(f"Embedding model: {model_name}")

    all_triples = None
    testing_triples = None

    # Load clinical target genes
    clinical_genes = load_clinical_targets(clinical_targets_dir)

    if dataset == 'hetionet':
        kg = Hetionet()
    elif dataset == 'biokg':
        kg = BioKG()
    elif dataset == 'openbiolink':
        kg = OpenBioLink()
    elif dataset == 'primekg':
        kg = PrimeKG()
    else:
        print(f'Dataset {dataset} is not recognised, please check it spelled correctly!')
        sys.exit(1)

    # Get entity and relation mappings
    entity_to_id = kg.training.entity_to_id
    relation_to_id = kg.training.relation_to_id
    
    # Map clinical gene symbols to KG entity label strings
    gene_entities = map_gene_symbols_to_entities(clinical_genes, entity_to_id, dataset)
    
    # Identify drug entity label strings
    drug_entities = identify_drug_entities(entity_to_id, dataset)
    
    # Filter each split to remove drug-gene interactions for clinical targets
    filtering_stats = {}
    
    if clinical_genes:
        print("\n" + "="*80)
        print("FILTERING STAGE - Removing drug-gene interactions for clinical targets")
        print("="*80)
        
        # Filter training triples
        print("\nFiltering training triples...")
        filtered_training, removed_training, train_stats = filter_drug_gene_triples(
            kg.training.triples, gene_entities, drug_entities,
            dataset_name=dataset, relation_to_id=relation_to_id
        )
        filtering_stats['training'] = train_stats
        
        # Filter testing triples
        print("\nFiltering testing triples...")
        filtered_testing, removed_testing, test_stats = filter_drug_gene_triples(
            kg.testing.triples, gene_entities, drug_entities,
            dataset_name=dataset, relation_to_id=relation_to_id
        )
        filtering_stats['testing'] = test_stats
        
        # Filter validation triples
        print("\nFiltering validation triples...")
        filtered_validation, removed_validation, val_stats = filter_drug_gene_triples(
            kg.validation.triples, gene_entities, drug_entities,
            dataset_name=dataset, relation_to_id=relation_to_id
        )
        filtering_stats['validation'] = val_stats
        
        # Save removed triples
        all_removed = np.concatenate([removed_training, removed_testing, removed_validation])
        removed_df = pd.DataFrame(all_removed, columns=['head', 'relation', 'tail'])
        splits = (['training'] * len(removed_training) + 
                  ['testing'] * len(removed_testing) + 
                  ['validation'] * len(removed_validation))
        removed_df['split'] = splits
        removed_df.to_csv('removed_triples.tsv', sep='\t', index=False)
        print(f"Removed triples saved to: removed_triples.tsv ({len(removed_df)} rows)")
        
        # Concatenate filtered triples
        all_triples = TriplesFactory.from_labeled_triples(
            np.concatenate([filtered_training, filtered_testing, filtered_validation])
        )
        testing_triples = TriplesFactory.from_labeled_triples(filtered_testing)
        
        # Write filtering statistics
        with open("filtering_stats.json", "w") as f:
            json.dump({
                'dataset': dataset,
                'clinical_genes_matched': len(gene_entities),
                'clinical_genes_total': len(clinical_genes),
                'drug_entities': len(drug_entities),
                'filtering_stats': filtering_stats
            }, f, indent=2)
        
        print("\n" + "="*80)
        print("FILTERING COMPLETE")
        print("="*80)
        print(f"Total triples removed: {sum(s['filtered'] for s in filtering_stats.values())}")
        print(f"Statistics saved to: filtering_stats.json")
    else:
        print("\n" + "="*80)
        print("NO FILTERING - No clinical targets provided")
        print("="*80)
        
        # Original behavior without filtering
        all_triples = TriplesFactory.from_labeled_triples(
            np.concatenate([
                kg.training.triples, 
                kg.testing.triples, 
                kg.validation.triples
            ])
        )
        testing_triples = kg.testing

    print(config["save"]["path"])

    # Include model name in save path
    save_path = os.path.join(config["save"]["path"], model_name)

    if all_triples is not None and testing_triples is not None:

        # Create a dummy file to check if CUDA is available
        # The script fails if CUDA is not available
        with open("cuda_version.txt", "w") as file:
            file.write(str(torch.zeros(1).cuda()))

        pipeline_result = pipeline(
            training=all_triples,
            testing=testing_triples,
            model=model_name,
            model_kwargs={
                "embedding_dim": config["model"]["embedding_dim"],
                "random_seed": config["seed"],
            },
            training_loop="sLCWA",
            training_kwargs={
                "num_epochs": config["train"]["num_epoch"],
            },
            optimizer=config["optimizer"]["class"],
            optimizer_kwargs={"lr": config["optimizer"]["lr"]},
            negative_sampler_kwargs={
                "num_negs_per_pos": config["train"]["num_negative"],
            },
            random_seed=config["seed"],
            evaluator_kwargs={"filtered": True},
        )
        pipeline_result.save_to_directory(save_path)

if __name__ == "__main__":
    main()
