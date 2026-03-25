process embedding {
    publishDir params.outdir, mode: 'copy'

    cpus 2
    memory { dataset == 'primekg' ? 24.GB : 12.GB }

    tag "${model}-${dataset}"

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

    if (params.skip_existing) {
        def existing = [] as Set
        try {
            datasets_to_run.each { ds ->
                def proc = ["aws", "s3", "ls", "${params.outdir}${ds}/"].execute()
                proc.waitFor()
                proc.text.readLines()
                    .findAll { it.trim().endsWith('/') }
                    .collect { it.trim().replaceAll(/.*PRE\s+/, '').replace('/', '') }
                    .each { mdl -> existing << "${ds}/${mdl}" }
            }
        } catch (Exception e) {
            log.warn "Could not check existing embeddings: ${e.message}. Running all combos."
        }

        combos = combos.findAll { mdl, ds, config ->
            def key = "${ds}/${mdl}"
            if (key in existing) {
                log.info "Skipping ${mdl}-${ds} - already exists in ${params.outdir}"
                return false
            }
            return true
        }
    }

    embedding(
        channel.fromList(combos),
        params.clinical_targets ?: 'NONE'
    )

}