process embedding {
    publishDir params.outdir, mode: 'copy'

    tag "${model}-${dataset}"

    cpus { dataset in ['openbiolink', 'primekg'] ? 8 : 4 }
    memory { dataset == 'primekg' ? 60.GB : dataset == 'openbiolink' ? 32.GB : 16.GB }

    input:
        tuple val(model), val(dataset), path(config)
        val clinical_targets_dir

    output:
        path '*'
  
    script:
    """
    generate_embeddings.py $dataset $config $clinical_targets_dir
    """
}

workflow {

    def all_datasets = ['hetionet', 'biokg', 'openbiolink', 'primekg']
    def all_models = ['RotatE', 'TransE', 'ComplEx', 'DistMult']

    def datasets_to_run = params.test_mode ? ['hetionet'] : (params.dataset ? [params.dataset] : all_datasets)
    def models_to_run = params.test_mode ? ['RotatE'] : (params.model == 'all' ? all_models : [params.model])

    def combos = datasets_to_run.collectMany { ds ->
        models_to_run.collect { mdl ->
            [mdl, ds, file("$projectDir/conf/${mdl}/${ds}.yaml")]
        }
    }

    embedding(
        channel.fromList(combos),
        params.clinical_targets ?: 'NONE'
    )

}