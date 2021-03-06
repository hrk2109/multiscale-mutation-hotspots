from copy import deepcopy
import json
import re
from flask import render_template
from maf_api_mock_data import EGFR_BLCA_BRCA as FAKE_MAF_DATA
from hotspots.seqpeek.tumor_types import tumor_types as ALL_TUMOR_TYPES

from app_logging import get_logger
log = get_logger()

try:
    from hotspots.seqpeek.gene_list import gene_list as GENE_LIST
except ImportError:
    log.error("Loading gene list failed, using static list.")
    GENE_LIST = ['EGFR', 'TP53', 'PTEN']

from hotspots.seqpeek.uniprot_data import get_uniprot_data
from hotspots.seqpeek.interpro_data import get_protein_domain_data
from hotspots.seqpeek.cluster_data import get_cluster_data as get_cluster_data_remote
from hotspots.seqpeek.mutation_data import get_mutation_data as get_mutation_data_remote
from hotspots.seqpeek.mutation_data import get_mutation_data_summary_for_gene

SEQPEEK_VIEW_DEBUG_MODE = False
SEQPEEK_VIEW_MUTATION_DEBUG = False

SAMPLE_ID_FIELD_NAME = 'patient_barcode'
TUMOR_TYPE_FIELD = "tumor"
COORDINATE_FIELD_NAME = 'amino_acid_position'

MUTATION_DATA_PROTEIN_FIELD = 'uniprot_id'

PROTEIN_DOMAIN_DB = 'PFAM'

ALPHA_FINDER = re.compile('[\W_]+', re.UNICODE)

TEMPLATE_NAME = 'hotspots/seqpeek/view.html'

def get_number_of_unique_samples(track):
    sample_ids = set()
    for mutation in track['mutations']:
        sample_ids.add(mutation[SAMPLE_ID_FIELD_NAME])

    return len(sample_ids)


# TODO remove if not needed
def clean_track_mutations(mutations_array):
    retval = []
    for mutation in mutations_array:
        cleaned = deepcopy(mutation)
        cleaned[COORDINATE_FIELD_NAME] = int(mutation[COORDINATE_FIELD_NAME])
        retval.append(cleaned)

    return retval


def sort_track_mutations(mutations_array):
    return sorted(mutations_array, key=lambda k: k[COORDINATE_FIELD_NAME])


def get_track_statistics(track):
    return {
        'samples': {
            'numberOf': get_number_of_unique_samples(track)
        }
    }


def filter_protein_domains(match_array):
    return [m for m in match_array if m['dbname'] == PROTEIN_DOMAIN_DB]


def get_table_row_id(tumor_type):
    return "seqpeek_row_{0}".format(tumor_type)


def build_seqpeek_regions(protein_data):
    return [{
        'type': 'exon',
        'start': 0,
        'end': protein_data['length']
    }]


def build_summary_track(tracks, render_summary_only=False):
    all = []
    for track in tracks:
        all.extend(track["mutations"])

    return {
        'mutations': all,
        'label': 'COMBINED',
        'tumor': 'none-combined',
        'type': 'summary',
        'do_variant_layout': True if render_summary_only is True else False
    }


def get_track_label(track):
    return track[TUMOR_TYPE_FIELD]


def process_raw_domain_data(data):
    result = []
    for item in data:
        database = item['database']

        # Filter for PFAM
        if not database.startswith('PF'):
            continue

        domain = {
            'name': item['name'][:5] + '...',
            'full_name': item['name'],
            'locations': [{
                'start': item['start'],
                'end': item['end']
            }],
            'dbname': 'PFAM',
            'ipr': {
                'type': 'Domain',
                'id': item['interpro_id'],
                'name': item['name'][:2]
            },
            'id': database
        }

        result.append(domain)

    log.debug("Found {total} domains, filtered down to {num}".format(total=len(data), num=len(result)))
    return result


def get_protein_domains_remote(uniprot_id):
    uniprot_data = get_uniprot_data(uniprot_id)
    log.debug("UniProt entry: " + str(uniprot_data))

    # Add protein domain data to the UniProt entry
    raw_domain_data = get_protein_domain_data(uniprot_id)
    domains = process_raw_domain_data(raw_domain_data)
    uniprot_data['matches'] = domains
    return uniprot_data


def get_protein_domains(uniprot_id):
    return get_protein_domains_remote(uniprot_id)


def get_maf_data_remote(gene, tumor_type_list):
    return get_mutation_data_remote(tumor_type_list, gene)


def get_mutation_data(gene, tumor_type_list):
    if SEQPEEK_VIEW_MUTATION_DEBUG:
        return deepcopy(FAKE_MAF_DATA['items'])
    else:
        return get_mutation_data_remote(tumor_type_list, gene)

def process_cluster_data_for_tumor(all_clusters, tumor_type):
    clusters = filter(lambda c: c['tumor_type'] == tumor_type, all_clusters)
    result = []
    for index, cluster in enumerate(clusters):
        item = {
            'name': '',
            'type': 'cluster',
            'id': 'cluster_' + str(index),
            'locations': [{
                'start': cluster['start'],
                'end': cluster['end']
            }],
            'mutation_stats': cluster['mutation_stats'],
            'stats': cluster['stats']
        }
        result.append(item)
    return result

def build_track_data(tumor_type_list, all_tumor_mutations, all_clusters):
    tracks = []
    for tumor_type in tumor_type_list:
        mutations = filter(lambda m: m['tumor_type'] == tumor_type, all_tumor_mutations);

        track_obj = {
            TUMOR_TYPE_FIELD: tumor_type,
            'mutations': mutations,
            'clusters': process_cluster_data_for_tumor(all_clusters, tumor_type),
            'do_variant_layout': True
        }

        if len(mutations) > 0:
            track_obj['render_in_seqpeek'] = True
        else:
            track_obj['render_in_seqpeek'] = False

        tracks.append(track_obj)

    return tracks

def find_uniprot_id(mutations):
    uniprot_id = None
    for m in mutations:
        if MUTATION_DATA_PROTEIN_FIELD in m:
            uniprot_id = m[MUTATION_DATA_PROTEIN_FIELD]
            break

    return uniprot_id

def get_cluster_data(tumor_type_array, gene):
    clusters = get_cluster_data_remote(tumor_type_array, gene)
    return clusters

def sanitize_gene_input(gene_parameter):
    return ALPHA_FINDER.sub('', gene_parameter)

def sanitize_normalize_tumor_type(tumor_type_list):
    tumor_set = frozenset(ALL_TUMOR_TYPES)
    sanitized = []
    for tumor_param in tumor_type_list:
        if tumor_param in tumor_set:
            sanitized.append(tumor_param)

    return sanitized

def format_tumor_type_list(tumor_type_array, selected_types=[]):
    result = []
    for tumor_type in tumor_type_array:
        result.append({
            'name': tumor_type,
            'selected': tumor_type in selected_types
        })

    return result

def seqpeek(request_gene, request_tumor_list, summary_only=False):
    gene = None
    if request_gene is not None:
        # Remove non-alphanumeric characters from parameters and uppercase all
        gene = sanitize_gene_input(request_gene).upper()

    parsed_tumor_list = sanitize_normalize_tumor_type(request_tumor_list)
    log.debug("Valid tumors from request: {0}".format(str(parsed_tumor_list)))

    tumor_types_for_tpl = format_tumor_type_list(ALL_TUMOR_TYPES, parsed_tumor_list)

    context = {
        'gene_select_widget': {
            'action': '/seqpeek',
            'tumor_type_select': True,
            'all_tumor_types': tumor_types_for_tpl,
            'button_label': 'Redraw'
        },
        'query_status': {
            'no_mutations_found': False,
            'uniprot_id_not_found': False,
            'data_found': False,
            'summary_only': False,
            'insufficient_parameters': False,
            'request_gene': request_gene
        },
        'gene_label': gene,
        'is_gene_summary': summary_only,
        'static_data': {
            'gene_list': GENE_LIST,
            'gene_label': gene,
            'fill_in_gene': True
        },
        'all_tumor_types': tumor_types_for_tpl
    }

    if (len(parsed_tumor_list) == 0 and summary_only is False) or gene is None:
        context['query_status']['insufficient_parameters'] = True
        context['static_data']['fill_in_gene'] = False
        context.update({
            'static_data': json.dumps(context['static_data'])
        })
        return render_template(TEMPLATE_NAME, **context)

    if summary_only is False:
        cluster_data = get_cluster_data(parsed_tumor_list, gene)
        maf_data = get_mutation_data(gene, parsed_tumor_list)
    else:
        maf_data = get_mutation_data_summary_for_gene(gene)

    if len(maf_data) == 0:
        context['query_status']['no_mutations_found'] = True
        context['static_data']['fill_in_gene'] = False
        context.update({
            'static_data': json.dumps(context['static_data'])
        })
        return render_template(TEMPLATE_NAME, **context)

    uniprot_id = find_uniprot_id(maf_data)

    if uniprot_id is None:
        context['query_status']['uniprot_id_not_found'] = True
        context['static_data']['fill_in_gene'] = False
        context.update({
            'static_data': json.dumps(context['static_data'])
        })
        return render_template(TEMPLATE_NAME, **context)

    log.debug("Found UniProt ID: " + repr(uniprot_id))

    context['query_status']['data_found'] = True

    protein_data = get_protein_domains(uniprot_id)

    plot_data = {
        'gene_label': gene,
        'protein': protein_data
    }

    if summary_only is False:
        track_data = build_track_data(parsed_tumor_list, maf_data, cluster_data)
        plot_data['tracks'] = track_data

        # Pre-processing
        # - Sort mutations by chromosomal coordinate
        for track in plot_data['tracks']:
            track['mutations'] = sort_track_mutations(track['mutations'])

        # Annotations
        # - Add label, possibly human readable
        # - Add type that indicates whether the track is driven by data from search or
        #   if the track is aggregate
        for track in plot_data['tracks']:
            track['type'] = 'tumor'
            track['label'] = get_track_label(track)

        plot_data['tracks'].append(build_summary_track(plot_data['tracks'], render_summary_only=False))

    else:
        summary_track = {
            'mutations': sort_track_mutations(maf_data)
        }
        plot_data['tracks'] = [build_summary_track([summary_track], render_summary_only=True)]

    for track in plot_data['tracks']:
        # Calculate statistics
        track['statistics'] = get_track_statistics(track)
        # Unique ID for each row
        track['render_info'] = {
            'row_id': get_table_row_id(track[TUMOR_TYPE_FIELD])
        }

    plot_data['regions'] = build_seqpeek_regions(plot_data['protein'])
    plot_data['protein']['matches'] = filter_protein_domains(plot_data['protein']['matches'])

    # Filter the tracks-array for Seqpeek. Only leave tracks with at least one mutation.
    seqpeek_data = {key: plot_data[key] for key in ['gene_label', 'protein', 'regions']}
    seqpeek_tracks = []
    for track in plot_data['tracks']:
        if len(track['mutations']) > 0:
            # Gene has to be passed to the track object, so that it can be used
            # to construct the URI for the pathway association view
            track['gene'] = gene
            seqpeek_tracks.append(track)
        else:
            log.debug("{0}: 0 mutations, not rendering in SeqPeek.".format(track['label']))

    seqpeek_data['tracks'] = seqpeek_tracks

    tumor_list = ','.join(parsed_tumor_list)

    context.update({
        'search': {},
        'plot_data': plot_data,
        'data_bundle': json.dumps(seqpeek_data),
        'gene': gene,
        'tumor_list': tumor_list
    })
    context.update({
        'static_data': json.dumps(context['static_data'])
    })

    return render_template(TEMPLATE_NAME, **context)

