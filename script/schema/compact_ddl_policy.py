"""Explicit, pure SHOW CREATE hashing policies; no database or filesystem I/O.

The legacy policy is byte-compatible with snapshot v1. The opt-in policy only
removes the redundant utf8mb4 character-set attribute whose adjacent binary
collation and complete column catalog already prove the same character set.
"""
from __future__ import annotations

import re


RAW_POLICY = 'RAW_SHOW_CREATE_V1'
CANONICAL_POLICY = 'CATALOG_VERIFIED_UTF8MB4_BIN_CHARSET_V1'
POLICIES = frozenset((RAW_POLICY, CANONICAL_POLICY))
STRING_TYPES = frozenset(('char', 'varchar', 'tinytext', 'text', 'mediumtext', 'longtext', 'enum', 'set'))
CONSTRAINT_START = frozenset(('primary', 'key', 'unique', 'constraint', 'foreign', 'check', 'fulltext', 'spatial'))


def _need(value, message):
    if not value:
        raise ValueError(message)


def _legacy_normalize(sql, schema):
    # Preserve this algorithm, including literal masking, for old v1 evidence.
    strings = []
    def save(match):
        strings.append(match.group(0)); return '\x01' + str(len(strings) - 1) + '\x02'
    masked = re.sub(r"'(?:''|\\.|[^'\\])*'|\"(?:\"\"|\\.|[^\"\\])*\"", save, sql)
    masked = re.sub(r'`' + re.escape(schema) + r'`\s*\.', '`$SELF`.', masked)
    return re.sub(r'\x01(\d+)\x02', lambda match: strings[int(match.group(1))], masked)


def _tokens(sql):
    """Return kind/value/start/end tokens without interpreting quoted values."""
    _need(type(sql) is str and 0 < len(sql.encode('utf8')) <= 16 * 1024 ** 2, 'Bounded complete CREATE TABLE text required')
    result, index = [], 0
    while index < len(sql):
        char, start = sql[index], index
        if char.isspace():
            index += 1
            continue
        if sql.startswith('/*', index):
            close = sql.find('*/', index + 2)
            _need(close >= 0, 'Unclosed DDL comment')
            index = close + 2
            result.append(('comment', None, start, index)); continue
        if char == '#' or (sql.startswith('--', index) and (index + 2 == len(sql) or sql[index + 2].isspace())):
            close = sql.find('\n', index)
            index = len(sql) if close < 0 else close
            result.append(('comment', None, start, index)); continue
        if char in ("'", '"', '`'):
            quote = char; index += 1; closed = False
            while index < len(sql):
                if quote != '`' and sql[index] == '\\':
                    index += 2
                elif sql[index] == quote:
                    index += 1
                    if index < len(sql) and sql[index] == quote:
                        index += 1
                    else:
                        closed = True; break
                else:
                    index += 1
            _need(closed, 'Unclosed quoted DDL token')
            value = sql[start + 1:index - 1].replace('``', '`') if quote == '`' else None
            result.append(('identifier' if quote == '`' else 'string', value, start, index)); continue
        if char.isalpha() or char in ('_', '$'):
            index += 1
            while index < len(sql) and (sql[index].isalnum() or sql[index] in ('_', '$')):
                index += 1
            result.append(('word', sql[start:index], start, index)); continue
        if char.isdigit():
            index += 1
            while index < len(sql) and (sql[index].isalnum() or sql[index] in ('_', '.', '$')):
                index += 1
            result.append(('number', sql[start:index], start, index)); continue
        index += 1
        result.append(('symbol', char, start, index))
    return result


def _create_parts(sql):
    tokens = _tokens(sql)
    significant = [token for token in tokens if token[0] != 'comment']
    _need(len(significant) >= 5 and [(t[0], (t[1] or '').lower()) for t in significant[:2]]
          == [('word', 'create'), ('word', 'table')], 'Only complete SHOW CREATE TABLE text is admitted')
    opening = next((i for i, token in enumerate(tokens) if token[:2] == ('symbol', '(')), None)
    _need(opening is not None, 'CREATE TABLE body required')
    head = [token for token in tokens[:opening] if token[0] != 'comment'][2:]
    if len(head) >= 3 and [str(token[1]).lower() for token in head[:3]] == ['if', 'not', 'exists']:
        head = head[3:]
    _need((len(head) == 1 and head[0][0] in ('identifier', 'word'))
          or (len(head) == 3 and head[0][0] in ('identifier', 'word')
              and head[1][:2] == ('symbol', '.') and head[2][0] in ('identifier', 'word')),
          'Explicit CREATE TABLE identifier required')
    depth, beginning, segments, closing = 1, opening + 1, [], None
    for index in range(opening + 1, len(tokens)):
        token = tokens[index]
        if token[:2] == ('symbol', '('):
            depth += 1
        elif token[:2] == ('symbol', ')'):
            depth -= 1
            if depth == 0:
                segments.append(tokens[beginning:index]); closing = index; break
            _need(depth > 0, 'Unbalanced CREATE TABLE body')
        elif token[:2] == ('symbol', ',') and depth == 1:
            segments.append(tokens[beginning:index]); beginning = index + 1
    _need(closing is not None and all(any(t[0] != 'comment' for t in segment) for segment in segments),
          'Complete nonempty CREATE TABLE column definitions required')
    return segments, tokens[closing + 1:]


def _columns(columns):
    _need(type(columns) is list and 0 < len(columns) <= 1024, 'Complete typed column catalog required')
    result = {}
    for column in columns:
        _need(type(column) is dict and type(column.get('name')) is str and column['name']
              and column['name'] not in result and 'charset' in column and 'collation' in column
              and (column['charset'] is None or type(column['charset']) is str)
              and (column['collation'] is None or type(column['collation']) is str), 'Unique complete column charset metadata required')
        result[column['name']] = column
    return result


def _column_segments(sql, columns):
    catalog = _columns(columns); segments, tail = _create_parts(sql)
    found = {}
    for segment in segments:
        tokens = [token for token in segment if token[0] != 'comment']
        first = tokens[0]
        if first[0] in ('identifier', 'word') and first[1] in catalog:
            _need(first[1] not in found and len(tokens) >= 2 and tokens[1][0] == 'word',
                  'Duplicate or incomplete catalog column definition')
            found[first[1]] = tokens
        else:
            _need(first[0] == 'word' and first[1].lower() in CONSTRAINT_START,
                  'CREATE TABLE columns differ from the complete catalog')
    _need(set(found) == set(catalog), 'CREATE TABLE columns differ from the complete catalog')
    return catalog, found, tail


def normalize_ddl(sql, schema, columns, policy=RAW_POLICY):
    """Normalize only the selected explicit policy; retain all other DDL bytes."""
    _need(type(policy) is str and policy in POLICIES, 'Unknown explicit DDL hash policy')
    _need(type(sql) is str and type(schema) is str and schema, 'Explicit DDL and schema text required')
    if policy == RAW_POLICY:
        return _legacy_normalize(sql, schema)
    catalog, segments, _ = _column_segments(sql, columns)
    remove = []
    for name, tokens in segments.items():
        column = catalog[name]
        if column['charset'] != 'utf8mb4' or column['collation'] != 'utf8mb4_bin' or tokens[1][1].lower() not in STRING_TYPES:
            continue
        index = 2
        if index < len(tokens) and tokens[index][:2] == ('symbol', '('):
            depth = 0
            for index in range(index, len(tokens)):
                if tokens[index][:2] == ('symbol', '('): depth += 1
                elif tokens[index][:2] == ('symbol', ')'):
                    depth -= 1
                    if depth == 0:
                        index += 1; break
            _need(depth == 0, 'Unclosed column type arguments')
        candidate = tokens[index:index + 5]
        if len(candidate) != 5 or any(token[0] != 'word' for token in candidate):
            continue
        if [token[1].lower() for token in candidate] != ['character', 'set', 'utf8mb4', 'collate', 'utf8mb4_bin']:
            continue
        # Never canonicalize through comments, defaults, expressions or literals.
        neighbors = [tokens[index - 1], *candidate]
        if not all(sql[left[3]:right[2]].isspace() for left, right in zip(neighbors, neighbors[1:])):
            continue
        start, end = candidate[0][2], candidate[2][3]
        if start > 0 and sql[start - 1] == ' ':
            start -= 1
        remove.append((start, end))
    for start, end in reversed(remove):
        sql = sql[:start] + sql[end:]
    return _legacy_normalize(sql, schema)


def table_auto_increment(ddl, columns):
    """Read the table-level actual next value, never a MAX(row) approximation."""
    catalog, segments, tail = _column_segments(ddl, columns)
    expected = set()
    actual = set()
    for name, column in catalog.items():
        _need(type(column.get('extra')) is str, 'Complete column EXTRA metadata required for auto increment')
        if re.search(r'(?:^|\s)auto_increment(?:\s|$)', column['extra'], re.I): expected.add(name)
        depth = 0
        for token in segments[name][1:]:
            if token[:2] == ('symbol', '('): depth += 1
            elif token[:2] == ('symbol', ')'): depth -= 1
            elif depth == 0 and token[0] == 'word' and token[1].lower() == 'auto_increment': actual.add(name)
    _need(expected == actual and len(expected) <= 1, 'AUTO_INCREMENT column metadata and DDL differ')
    significant = [token for token in tail if token[0] != 'comment']
    options, depth = [], 0
    for index, token in enumerate(significant):
        if token[:2] == ('symbol', '('): depth += 1
        elif token[:2] == ('symbol', ')'):
            depth -= 1; _need(depth >= 0, 'Unbalanced CREATE TABLE options')
        elif depth == 0 and token[0] == 'word' and token[1].lower() == 'auto_increment':
            following = significant[index + 1:index + 3]
            _need(len(following) == 2 and following[0][:2] == ('symbol', '=') and following[1][0] == 'number'
                  and re.fullmatch(r'[1-9][0-9]{0,19}', following[1][1])
                  and int(following[1][1]) <= 2 ** 64 - 1, 'Canonical positive table AUTO_INCREMENT required')
            end = index + 3
            _need(end == len(significant) or significant[end][0] == 'word' or significant[end][:2] == ('symbol', ';'),
                  'Complete table AUTO_INCREMENT option required')
            options.append(following[1][1])
    _need(depth == 0 and len(options) <= 1 and (not options or len(expected) == 1),
          'One table AUTO_INCREMENT option requires exactly one matching auto column')
    return options[0] if options else '1' if expected else None
