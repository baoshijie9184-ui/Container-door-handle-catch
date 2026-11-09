"""Exact charset canonicalization and high-water policy tests for ECS CI."""
import importlib.util
from pathlib import Path

import pytest


FILE = Path(__file__).resolve().parents[1] / 'script/schema/compact_ddl_policy.py'
SPEC = importlib.util.spec_from_file_location('compact_ddl_policy_tests', FILE)
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


def column(name='payload', *, charset='utf8mb4', collation='utf8mb4_bin', extra=''):
    return {'name': name, 'charset': charset, 'collation': collation, 'extra': extra}


def columns():
    return [column('id', charset=None, collation=None, extra='auto_increment'), column()]


def ddl(*, charset=True, data_type='varchar(32)', tail='AUTO_INCREMENT=10', attributes='NOT NULL', name='payload'):
    declaration = data_type + (' CHARACTER SET utf8mb4' if charset else '') + ' COLLATE utf8mb4_bin '
    return ('CREATE TABLE `legacy`.`items` (\n  `id` bigint NOT NULL AUTO_INCREMENT,\n  `'
            + name + '` ' + declaration + attributes + ',\n  PRIMARY KEY (`id`)\n) ENGINE=InnoDB '
            + tail + ' DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin')


def normalize(sql, metadata=None):
    return policy.normalize_ddl(sql, 'legacy', columns() if metadata is None else metadata, policy.CANONICAL_POLICY)


def test_default_policy_preserves_raw_v1_bytes_except_legacy_schema_normalization():
    sql = r'''CREATE TABLE `legacy` .`items` (`payload` varchar(40) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT 'keep `legacy` . and \' quote', CHECK (`legacy` .`items`.`payload` <> "`legacy` ."))'''
    expected = r'''CREATE TABLE `$SELF`.`items` (`payload` varchar(40) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT 'keep `legacy` . and \' quote', CHECK (`$SELF`.`items`.`payload` <> "`legacy` ."))'''
    assert policy.normalize_ddl(sql, 'legacy', None) == expected
    assert policy.normalize_ddl(sql, 'legacy', None, policy.RAW_POLICY) == expected


def test_raw_policy_does_not_reinterpret_or_repair_an_old_unparsed_document():
    sql = "opaque old text '`legacy`.' and `legacy` .`field`"
    assert policy.normalize_ddl(sql, 'legacy', None) == "opaque old text '`legacy`.' and `$SELF`.`field`"


def test_proven_redundant_charset_has_one_canonical_form_and_preserves_collation():
    before = ddl(charset=False)
    after = ddl(charset=True)
    expected = policy.normalize_ddl(before, 'legacy', None, policy.RAW_POLICY)
    assert normalize(before) == normalize(after) == expected
    assert 'COLLATE utf8mb4_bin' in normalize(after)


@pytest.mark.parametrize('data_type', ['char(4)', 'varchar(32)', 'tinytext', 'text', 'mediumtext', 'longtext',
    "enum('alpha,beta','literal ) and CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')", "set('alpha','beta')"])
def test_supported_string_type_prefixes_are_canonicalized_without_entering_type_literals(data_type):
    assert normalize(ddl(data_type=data_type)) == normalize(ddl(data_type=data_type, charset=False))


@pytest.mark.parametrize(('charset', 'collation'), [('latin1', 'latin1_bin'), ('utf8mb4', 'utf8mb4_0900_ai_ci'),
                                                    (None, None), ('utf8', 'utf8_bin')])
def test_catalog_must_prove_the_exact_character_set_and_binary_collation(charset, collation):
    metadata = columns(); metadata[1].update(charset=charset, collation=collation)
    assert normalize(ddl(), metadata) == policy.normalize_ddl(ddl(), 'legacy', None)


def test_a_real_declared_character_set_or_collation_change_is_not_erased():
    sql = ddl().replace('CHARACTER SET utf8mb4 COLLATE utf8mb4_bin', 'CHARACTER SET latin1 COLLATE latin1_bin')
    assert normalize(sql) == policy.normalize_ddl(sql, 'legacy', None)
    assert normalize(sql) != normalize(ddl())


@pytest.mark.parametrize('attributes', [
    "DEFAULT 'CHARACTER SET utf8mb4 COLLATE utf8mb4_bin' COMMENT 'same CHARACTER SET utf8mb4'",
    'DEFAULT "CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"',
    "GENERATED ALWAYS AS (concat('CHARACTER SET utf8mb4 COLLATE utf8mb4_bin', `id`)) STORED",
])
def test_defaults_comments_and_generated_expressions_remain_exact(attributes):
    value = normalize(ddl(attributes=attributes))
    assert attributes in value
    assert value == normalize(ddl(charset=False, attributes=attributes))


def test_expression_only_character_set_tokens_are_not_treated_as_column_attributes():
    sql = ('CREATE TABLE `items` (`payload` varchar(32) GENERATED ALWAYS AS '
           '(cast(1 AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_bin)) ENGINE=InnoDB')
    assert normalize(sql, [column()]) == sql


def test_table_comments_and_constraints_are_never_rewritten_as_column_declarations():
    sql = ddl() + " COMMENT='CHARACTER SET utf8mb4 COLLATE utf8mb4_bin'"
    sql = sql.replace('PRIMARY KEY (`id`)', "PRIMARY KEY (`id`), CHECK (`payload` <> 'CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')")
    actual = normalize(sql)
    assert "CHECK (`payload` <> 'CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')" in actual
    assert actual.endswith("COMMENT='CHARACTER SET utf8mb4 COLLATE utf8mb4_bin'")


def test_canonicalization_does_not_cross_a_comment_to_remove_tokens():
    sql = ddl().replace('CHARACTER SET utf8mb4', 'CHARACTER /* keep */ SET utf8mb4')
    assert normalize(sql) == policy.normalize_ddl(sql, 'legacy', None)


def test_leading_sql_comments_remain_unmodified_while_table_body_is_understood():
    prefix = '/* retained opaque note */\n'
    assert normalize(prefix + ddl()) == prefix + normalize(ddl())


def test_multiple_columns_are_matched_by_exact_name_instead_of_catalog_order():
    sql = ('CREATE TABLE `items` (`left` varchar(8) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin, '
           '`right` text CHARACTER SET utf8mb4 COLLATE utf8mb4_bin) ENGINE=InnoDB')
    metadata = [column('right'), column('left')]
    assert normalize(sql, metadata) == sql.replace(' CHARACTER SET utf8mb4', '')


@pytest.mark.parametrize('metadata', [None, [], [column(), column()], [column('wrong')],
                                      [{'name': 'payload', 'charset': 'utf8mb4'}]])
def test_new_policy_requires_complete_unique_catalog_columns(metadata):
    with pytest.raises(ValueError):
        policy.normalize_ddl(ddl(), 'legacy', metadata, policy.CANONICAL_POLICY)


@pytest.mark.parametrize('text', ['CREATE VIEW v AS SELECT 1', 'CREATE TABLE `items` (`payload` text',
                                  "CREATE TABLE `items` (`payload` text COMMENT 'unclosed)",
                                  'CREATE TABLE `items` (`payload` text, `unknown` text)'])
def test_unknown_or_incomplete_structure_is_refused_instead_of_globally_replaced(text):
    with pytest.raises(ValueError):
        normalize(text, [column()])


@pytest.mark.parametrize('name', ['future-policy', '', None, 1, True])
def test_unknown_policy_is_never_silently_interpreted_as_legacy(name):
    with pytest.raises(ValueError, match='Unknown explicit DDL hash policy'):
        policy.normalize_ddl(ddl(), 'legacy', columns(), name)


def test_table_high_water_comes_from_outer_option_and_not_row_values_or_literals():
    sql = ddl(tail='AUTO_INCREMENT=35') + " COMMENT='AUTO_INCREMENT=999'"
    assert policy.table_auto_increment(sql, columns()) == '35'


def test_auto_column_without_an_explicit_table_option_has_exact_empty_start_value_one():
    assert policy.table_auto_increment(ddl(tail=''), columns()) == '1'


def test_table_without_any_auto_column_has_no_high_water_even_with_token_text_in_literals():
    sql = "CREATE TABLE `items` (`payload` text COMMENT 'AUTO_INCREMENT=999') ENGINE=InnoDB"
    assert policy.table_auto_increment(sql, [column()]) is None


@pytest.mark.parametrize('value', ['0', '-1', '+1', '01', '1.5', '1e2', '1 + 2', '18446744073709551616'])
def test_table_high_water_requires_one_canonical_uint64_decimal(value):
    with pytest.raises(ValueError):
        policy.table_auto_increment(ddl(tail='AUTO_INCREMENT=' + value), columns())


def test_maximum_uint64_high_water_is_preserved_without_numeric_rounding():
    assert policy.table_auto_increment(ddl(tail='AUTO_INCREMENT=18446744073709551615'), columns()) == '18446744073709551615'


def test_duplicate_table_high_water_options_are_refused_even_when_equal():
    with pytest.raises(ValueError):
        policy.table_auto_increment(ddl(tail='AUTO_INCREMENT=10 AUTO_INCREMENT=10'), columns())


def test_an_auto_option_cannot_create_authority_for_a_table_without_auto_columns():
    with pytest.raises(ValueError):
        policy.table_auto_increment('CREATE TABLE `items` (`payload` text) ENGINE=InnoDB AUTO_INCREMENT=10', [column()])


@pytest.mark.parametrize('extra', ['', 'generated_auto_increment_text'])
def test_actual_auto_column_and_catalog_extra_must_agree(extra):
    metadata = columns(); metadata[0]['extra'] = extra
    with pytest.raises(ValueError):
        policy.table_auto_increment(ddl(), metadata)


def test_multiple_auto_columns_are_refused_without_guessing_which_counter_applies():
    sql = ('CREATE TABLE `items` (`id` bigint AUTO_INCREMENT, `other` bigint AUTO_INCREMENT) '
           'ENGINE=InnoDB AUTO_INCREMENT=10')
    metadata = [column('id', charset=None, collation=None, extra='auto_increment'),
                column('other', charset=None, collation=None, extra='auto_increment')]
    with pytest.raises(ValueError):
        policy.table_auto_increment(sql, metadata)


def test_high_water_comparison_requires_explicit_complete_extra_metadata():
    metadata = columns(); metadata[0].pop('extra')
    with pytest.raises(ValueError):
        policy.table_auto_increment(ddl(), metadata)
