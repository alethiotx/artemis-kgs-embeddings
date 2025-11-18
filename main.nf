process embedding {
    publishDir params.outdir, mode: 'copy'

    input:
        path config
        val dataset

    output:
        path '*'
  
    script:
    """
    #!/usr/bin/env python3

    from pykeen.pipeline import pipeline
    from pykeen.datasets import Hetionet, BioKG, OpenBioLink, PrimeKG
    from pykeen.triples import TriplesFactory
    import numpy as np
    import sys
    import yaml
    import torch

    def load_config(config_path: str) -> dict:
        with open(config_path, "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)
        return config

    dataset = "$dataset"
    config_path = "$config"

    config: dict = load_config(config_path)

    all_triples = None
    testing_triples = None

    if dataset == 'hetionet':
        kg = Hetionet()
    
    if dataset == 'biokg':
        kg = BioKG()

    if dataset == 'openbiolink':
        kg = OpenBioLink()

    if dataset == 'primekg':
        kg = PrimeKG()

    all_triples = TriplesFactory.from_labeled_triples(
        np.concatenate([
            kg.training.triples, 
            kg.testing.triples, 
            kg.validation.triples
        ])
    )
    testing_triples = kg.testing

    print(config["save"]["path"])

    if all_triples and testing_triples:

        # Create a dummy file to check if CUDA is available
        # The script fails if CUDA is not available
        with open("cuda_version.txt", "w") as file:
            file.write(str(torch.zeros(1).cuda()))

        pipeline_result = pipeline(
            training=all_triples,
            testing=testing_triples,
            model=config["model"]["name"],
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
        pipeline_result.save_to_directory(config["save"]["path"])

    else:
        print('Dataset ' + dataset + ' is not recognised, please check it spelled correctly!')
    """
}

workflow {

    embedding(
        file(params.config),
        params.dataset
    )

}