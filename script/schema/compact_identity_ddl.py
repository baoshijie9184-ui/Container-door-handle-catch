"""Closed compact identity protocols and generated lookup columns; no database execution.

The baseline author incorporates these definitions. Source unsigned IDs are preserved
as decimal payload strings and remain independent of shared physical row cursors.
"""

WORKFLOW_KINDS = (
    'DETECTION_IDENTITY_COMMAND', 'DETECTION_IDENTITY_MAP_BATCH',
    'DETECTION_IDENTITY_MAP_ITEM', 'DETECTION_IDENTITY_REPORT',
)
AUDIT_KINDS = (
    'DETECTION_ASSIGNMENT_IDENTITY', 'DETECTION_IDENTITY_BINDING_EVENT',
    'DETECTION_IDENTITY_RECON_ITEM', 'DETECTION_IDENTITY_MISSING_NAME',
)
RUNTIME_NAMESPACES = (
    'DETECTION_IDENTITY_CONTROL', 'DETECTION_IDENTITY_SOURCE_CONTROL',
    'DETECTION_IDENTITY_BINDING',
)

# Each stored V1 object contains exactly these keys, including explicit JSON nulls.
FIELDS = {
    'DETECTION_IDENTITY_CONTROL': ['controlId', 'activationRevision', 'legacySource'],
    'DETECTION_IDENTITY_SOURCE_CONTROL': ['controlId', 'activationRevision', 'legacySource'],
    'DETECTION_IDENTITY_BINDING': ['taskId', 'identityRole', 'eventSha256', 'legacyId', 'legacyEventId', 'legacySource'],
    'DETECTION_IDENTITY_COMMAND': ['actorUserId', 'legacyCreatedAt'],
    'DETECTION_IDENTITY_MAP_BATCH': ['actorUserId', 'actorName', 'revisionBefore', 'revisionAfter', 'appliedCount', 'legacyId', 'legacyCreatedAt'],
    'DETECTION_IDENTITY_MAP_ITEM': ['batchId', 'taskId', 'identityRole', 'sourceName', 'sourceSnapshot', 'previousUserId', 'previousIdentityName', 'targetUserId', 'targetUsername', 'targetRole', 'targetRevision', 'confirmationBasis', 'legacyId'],
    'DETECTION_IDENTITY_REPORT': ['actorUserId', 'actorName', 'protocol', 'controlRevision', 'identityMode', 'sourceMode', 'startedAt', 'finishedAt', 'taskCount', 'roleCount', 'issueCount', 'datasetSha256', 'previousReportId', 'summaryJson', 'legacyId'],
    'DETECTION_ASSIGNMENT_IDENTITY': ['taskId', 'actorUserId', 'actorName', 'assigneeUserId', 'assigneeName', 'assigneeRevision', 'requestId', 'legacyId', 'legacyCreatedAt'],
    'DETECTION_IDENTITY_BINDING_EVENT': ['taskId', 'identityRole', 'boundUserId', 'boundIdentityName', 'targetRevision', 'actorUserId', 'actorName', 'sourceKind', 'requestId', 'sourceBatchId', 'legacyId', 'legacyCreatedAt'],
    'DETECTION_IDENTITY_RECON_ITEM': ['reportId', 'taskId', 'identityRole', 'existingName', 'existingUserId', 'identityName', 'currentUsername', 'currentRole', 'currentRevision', 'sourceKind', 'sourceRequestId', 'sourceSha256', 'reasonCodes', 'itemSha256', 'legacyId'],
    'DETECTION_IDENTITY_MISSING_NAME': ['batchId', 'taskId', 'identityRole', 'originalName', 'sourceSnapshot', 'targetUserId', 'evidenceReference', 'legacyCreatedAt'],
}

INTEGER_FIELDS = {
    'controlId', 'activationRevision', 'actorUserId', 'revisionBefore', 'revisionAfter',
    'appliedCount', 'previousUserId', 'targetUserId', 'controlRevision', 'taskCount',
    'roleCount', 'issueCount', 'assigneeUserId', 'boundUserId', 'existingUserId',
}
UNSIGNED_TEXT_FIELDS = {'legacyId', 'legacyEventId', 'batchId', 'sourceBatchId', 'reportId', 'previousReportId'}
STRING_WIDTHS = {
    'taskId': 128, 'identityRole': 24, 'eventSha256': 64, 'legacySource': 64,
    'legacyCreatedAt': 32, 'actorName': 64, 'sourceName': 64, 'sourceSnapshot': 64,
    'previousIdentityName': 64, 'targetUsername': 64, 'targetRole': 24,
    'targetRevision': 64, 'confirmationBasis': 32, 'protocol': 48,
    'identityMode': 16, 'sourceMode': 16, 'startedAt': 32, 'finishedAt': 32,
    'datasetSha256': 64, 'assigneeName': 64, 'assigneeRevision': 64,
    'requestId': 128, 'boundIdentityName': 64, 'sourceKind': 32,
    'existingName': 64, 'identityName': 64, 'currentUsername': 64,
    'currentRole': 24, 'currentRevision': 64, 'sourceRequestId': 128,
    'sourceSha256': 64, 'itemSha256': 64, 'originalName': 64,
    'evidenceReference': 128,
}
NULLABLE = {
    'DETECTION_IDENTITY_CONTROL': {'activationRevision', 'legacySource'},
    'DETECTION_IDENTITY_SOURCE_CONTROL': {'activationRevision', 'legacySource'},
    'DETECTION_IDENTITY_BINDING': {'legacyId', 'legacyEventId', 'legacySource'},
    'DETECTION_IDENTITY_COMMAND': {'legacyCreatedAt'},
    'DETECTION_IDENTITY_MAP_BATCH': {'legacyId', 'legacyCreatedAt'},
    'DETECTION_IDENTITY_MAP_ITEM': {'previousUserId', 'previousIdentityName', 'legacyId'},
    'DETECTION_IDENTITY_REPORT': {'previousReportId', 'legacyId'},
    'DETECTION_ASSIGNMENT_IDENTITY': {'legacyId', 'legacyCreatedAt'},
    'DETECTION_IDENTITY_BINDING_EVENT': {'boundUserId', 'boundIdentityName', 'targetRevision', 'actorUserId', 'actorName', 'sourceBatchId', 'legacyId', 'legacyCreatedAt'},
    'DETECTION_IDENTITY_RECON_ITEM': {'existingName', 'existingUserId', 'identityName', 'currentUsername', 'currentRole', 'currentRevision', 'sourceKind', 'sourceRequestId', 'sourceSha256', 'legacyId'},
    'DETECTION_IDENTITY_MISSING_NAME': {'originalName', 'legacyCreatedAt'},
}


def _s(field):
    return f"CASE WHEN JSON_TYPE(JSON_EXTRACT(payload_json,'$.{field}'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.{field}')) END"


def lookup_columns(table):
    """Return column definitions only; the owner chooses baseline insertion points."""
    discriminator = 'namespace' if table == 'runtime_state' else 'kind'
    kinds = RUNTIME_NAMESPACES if table == 'runtime_state' else WORKFLOW_KINDS if table == 'workflow_instance' else AUDIT_KINDS
    eligible = ','.join("'" + x + "'" for x in kinds)
    result = [
        f"identity_task_id VARCHAR(128) COLLATE utf8mb4_bin GENERATED ALWAYS AS (CASE WHEN {discriminator} IN ({eligible}) THEN {_s('taskId')} END) VIRTUAL",
        f"identity_role VARCHAR(24) COLLATE utf8mb4_bin GENERATED ALWAYS AS (CASE WHEN {discriminator} IN ({eligible}) THEN {_s('identityRole')} END) VIRTUAL",
    ]
    if table != 'runtime_state':
        result.append(f"identity_source_id BIGINT UNSIGNED GENERATED ALWAYS AS (CASE WHEN kind IN ({eligible}) AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.legacyId'))='STRING' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.legacyId')) AS UNSIGNED) END) VIRTUAL")
        result.append("identity_parent_id BIGINT UNSIGNED GENERATED ALWAYS AS (CASE kind WHEN 'DETECTION_IDENTITY_MAP_ITEM' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.batchId')) AS UNSIGNED) WHEN 'DETECTION_IDENTITY_MISSING_NAME' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.batchId')) AS UNSIGNED) WHEN 'DETECTION_IDENTITY_BINDING_EVENT' THEN CASE WHEN JSON_TYPE(JSON_EXTRACT(payload_json,'$.sourceBatchId'))='STRING' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.sourceBatchId')) AS UNSIGNED) END WHEN 'DETECTION_IDENTITY_RECON_ITEM' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.reportId')) AS UNSIGNED) END) VIRTUAL")
        result += [
            'UNIQUE KEY uk_identity_source_id (kind,identity_source_id)',
            'KEY ix_identity_task_role (kind,identity_task_id,identity_role,id)',
            'KEY ix_identity_parent (kind,identity_parent_id,id)',
        ]
    if table == 'workflow_instance':
        result += [
            "identity_protocol VARCHAR(48) COLLATE utf8mb4_bin GENERATED ALWAYS AS (CASE WHEN kind='DETECTION_IDENTITY_REPORT' THEN " + _s('protocol') + ' END) VIRTUAL',
            'UNIQUE KEY uk_identity_map_item (kind,identity_parent_id,identity_task_id,identity_role)',
            'KEY ix_identity_report_protocol (kind,identity_protocol,id)',
        ]
    elif table == 'audit_event':
        result += [
            "identity_child_parent_id BIGINT UNSIGNED GENERATED ALWAYS AS (CASE WHEN kind IN ('DETECTION_IDENTITY_RECON_ITEM','DETECTION_IDENTITY_MISSING_NAME') THEN identity_parent_id END) VIRTUAL",
            "identity_actor_key BIGINT GENERATED ALWAYS AS (CASE WHEN kind='DETECTION_ASSIGNMENT_IDENTITY' AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.actorUserId'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.actorUserId')) AS SIGNED) END) VIRTUAL",
            "identity_assignment_request_id VARCHAR(128) COLLATE utf8mb4_bin GENERATED ALWAYS AS (CASE WHEN kind='DETECTION_ASSIGNMENT_IDENTITY' THEN " + _s('requestId') + ' END) VIRTUAL',
            'UNIQUE KEY uk_identity_child_evidence (kind,identity_child_parent_id,identity_task_id,identity_role)',
            'UNIQUE KEY uk_identity_assignment_request (identity_actor_key,identity_assignment_request_id,identity_task_id)',
        ]
    else:
        result += [
            "identity_head_event_ref VARCHAR(180) COLLATE utf8mb4_bin GENERATED ALWAYS AS (CASE WHEN namespace='DETECTION_IDENTITY_BINDING' THEN current_ref END) VIRTUAL",
            'UNIQUE KEY uk_identity_binding (namespace,identity_task_id,identity_role)',
            'UNIQUE KEY uk_identity_head_event (namespace,identity_head_event_ref)',
        ]
    return result


def closed_object(kind):
    keys = FIELDS[kind]
    paths = ','.join("'$." + key + "'" for key in keys)
    terms = [f"payload_version=1 AND JSON_TYPE(CAST(payload_json AS JSON))='OBJECT' "
             f"AND JSON_LENGTH(payload_json)={len(keys)} AND JSON_CONTAINS_PATH(payload_json,'all',{paths})=1"]
    for field in keys:
        value = "JSON_EXTRACT(payload_json,'$." + field + "')"
        text = 'JSON_UNQUOTE(' + value + ')'
        if field in INTEGER_FIELDS:
            limit = ('-2147483648 AND 2147483647' if field in ('controlId', 'appliedCount')
                     else '-9223372036854775808 AND 9223372036854775807')
            expression = "JSON_TYPE(" + value + ")='INTEGER' AND CAST(" + text + ' AS DECIMAL(20,0)) BETWEEN ' + limit
        elif field in UNSIGNED_TEXT_FIELDS:
            expression = ("JSON_TYPE(" + value + ")='STRING' AND " + text
                          + " REGEXP '^(0|[1-9][0-9]{0,19})$' AND CAST(" + text
                          + ' AS DECIMAL(20,0))<=18446744073709551615')
        elif field in ('summaryJson', 'reasonCodes'):
            expression = "JSON_TYPE(" + value + ")='STRING' AND JSON_VALID(" + text + ')'
        else:
            width = STRING_WIDTHS[field]
            # Original VARCHAR NOT NULL permits the empty string. Preserve bad old evidence,
            # while application writes continue to validate roles, accounts and requests.
            expression = "JSON_TYPE(" + value + ")='STRING' AND CHAR_LENGTH(" + text + ')<=' + str(width)
            if field == 'legacySource':
                legacy = {'DETECTION_IDENTITY_CONTROL': 'detection_identity_control',
                          'DETECTION_IDENTITY_SOURCE_CONTROL': 'detection_identity_source_control',
                          'DETECTION_IDENTITY_BINDING': 'detection_identity_binding'}[kind]
                expression += " AND BINARY " + text + "=BINARY '" + legacy + "'"
        if field in NULLABLE[kind]:
            expression = "JSON_TYPE(" + value + ")='NULL' OR (" + expression + ')'
        terms.append('(' + expression + ')')
    return ' AND '.join(terms)


# Required source-clock exceptions, never a general relaxation:
# runtime UNKNOWN updated_at: legacySource exactly control/source_control/binding,
# with legacySource matching the namespace and created_at NULL.
# workflow MAP_ITEM: created_at/updated_at/finished_at NULL only legacy_source exact
# detection_identity_mapping_item with preserved legacy_key.
# audit RECON_ITEM: occurred_at NULL only exact detection_identity_reconciliation_item.
# Legacy rows without a valid positive actor keep raw actorUserId in the payload;
# shared owner may be 0 (workflow) / NULL (audit) only with the exact imported source.
