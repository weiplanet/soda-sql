#  Copyright 2020 Soda
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#   http://www.apache.org/licenses/LICENSE-2.0
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
import re
from typing import List, Optional, Set

from jinja2 import Template

from sodasql.scan.file_system import FileSystemSingleton
from sodasql.scan.metric import Metric
from sodasql.scan.missing import Missing
from sodasql.scan.parser import Parser
from sodasql.scan.samples_yml import SamplesYml
from sodasql.scan.scan_yml import ScanYml
from sodasql.scan.scan_yml_column import ScanYmlColumn
from sodasql.scan.sql_metric_yml import SqlMetricYml
from sodasql.scan.test import Test
from sodasql.scan.validity import Validity

KEY_TABLE_NAME = 'table_name'
KEY_METRICS = 'metrics'
KEY_METRIC_GROUPS = 'metric_groups'
KEY_SQL_METRICS = 'sql_metrics'
KEY_TESTS = 'tests'
KEY_COLUMNS = 'columns'
KEY_MINS_MAXS_LIMIT = 'mins_maxs_limit'
KEY_FREQUENT_VALUES_LIMIT = 'frequent_values_limit'
KEY_SAMPLE_PERCENTAGE = 'sample_percentage'
KEY_SAMPLE_METHOD = 'sample_method'
KEY_FILTER = 'filter'
KEY_SAMPLES = 'samples'

VALID_SCAN_YML_KEYS = [KEY_TABLE_NAME, KEY_METRICS, KEY_METRIC_GROUPS, KEY_SQL_METRICS,
                       KEY_TESTS, KEY_COLUMNS, KEY_MINS_MAXS_LIMIT, KEY_FREQUENT_VALUES_LIMIT,
                       KEY_SAMPLE_PERCENTAGE, KEY_SAMPLE_METHOD, KEY_FILTER, KEY_SAMPLES]

COLUMN_KEY_METRICS = KEY_METRICS
COLUMN_KEY_METRIC_GROUPS = KEY_METRIC_GROUPS
COLUMN_KEY_SQL_METRICS = KEY_SQL_METRICS
COLUMN_KEY_TESTS = KEY_TESTS
COLUMN_KEY_SAMPLES = KEY_SAMPLES

COLUMN_KEY_MISSING_VALUES = 'missing_values'
COLUMN_KEY_MISSING_FORMAT = 'missing_format'
COLUMN_KEY_MISSING_REGEX = 'missing_regex'

COLUMN_KEY_VALID_FORMAT = 'valid_format'
COLUMN_KEY_VALID_REGEX = 'valid_regex'
COLUMN_KEY_VALID_VALUES = 'valid_values'
COLUMN_KEY_VALID_MIN = 'valid_min'
COLUMN_KEY_VALID_MAX = 'valid_max'
COLUMN_KEY_VALID_MIN_LENGTH = 'valid_min_length'
COLUMN_KEY_VALID_MAX_LENGTH = 'valid_max_length'

COLUMN_MISSING_KEYS = [
    COLUMN_KEY_MISSING_VALUES,
    COLUMN_KEY_MISSING_FORMAT,
    COLUMN_KEY_MISSING_REGEX]

COLUMN_VALID_KEYS = [
    COLUMN_KEY_VALID_FORMAT,
    COLUMN_KEY_VALID_REGEX,
    COLUMN_KEY_VALID_VALUES,
    COLUMN_KEY_VALID_MIN,
    COLUMN_KEY_VALID_MAX,
    COLUMN_KEY_VALID_MIN_LENGTH,
    COLUMN_KEY_VALID_MAX_LENGTH]

VALID_COLUMN_KEYS = COLUMN_MISSING_KEYS + COLUMN_VALID_KEYS + [
    COLUMN_KEY_METRICS,
    COLUMN_KEY_METRIC_GROUPS,
    COLUMN_KEY_SQL_METRICS,
    COLUMN_KEY_TESTS,
    COLUMN_KEY_SAMPLES]

SAMPLES_KEY_DATASET_LIMIT = 'table_limit'
SAMPLES_KEY_DATASET_TABLESAMPLE = 'table_tablesample'
SAMPLES_KEY_FAILED_LIMIT = 'failed_limit'
SAMPLES_KEY_FAILED_TABLESAMPLE = 'failed_tablesample'
SAMPLES_KEY_PASSED_LIMIT = 'passed_limit'
SAMPLES_KEY_PASSED_TABLESAMPLE = 'passed_tablesample'

SQL_METRIC_KEY_NAME = 'name'
SQL_METRIC_KEY_TITLE = 'title'
SQL_METRIC_KEY_SQL = 'sql'
SQL_METRIC_KEY_TYPE = 'type'
SQL_METRIC_KEY_SQL_FILE = 'sql_file'
SQL_METRIC_KEY_METRIC_NAMES = 'metric_names'
SQL_METRIC_KEY_TESTS = KEY_TESTS
SQL_METRIC_KEY_GROUP_FIELDS = 'group_fields'
SQL_METRIC_KEY_FAILED_LIMIT = SAMPLES_KEY_FAILED_LIMIT

VALID_SQL_METRIC_KEYS = [SQL_METRIC_KEY_SQL, SQL_METRIC_KEY_METRIC_NAMES, SQL_METRIC_KEY_TESTS,
                         SQL_METRIC_KEY_SQL_FILE, SQL_METRIC_KEY_GROUP_FIELDS, SQL_METRIC_KEY_FAILED_LIMIT]


class ScanYmlParser(Parser):

    def __init__(self,
                 scan_yml_dict: dict,
                 scan_yml_path: str = 'scan'):
        super().__init__(description=scan_yml_path)

        self.scan_yaml_path = scan_yml_path

        self.scan_yml = ScanYml()

        self._push_context(scan_yml_dict, self.description)

        table_name = self.get_str_required(KEY_TABLE_NAME)
        self.scan_yml.table_name = table_name
        self.scan_yml.metrics = self.parse_metrics()

        self.scan_yml.sql_metric_ymls = self.parse_sql_metric_ymls(KEY_SQL_METRICS)

        self.scan_yml.tests = self.parse_tests(scan_yml_dict, KEY_TESTS, context_table_name=table_name)
        self.scan_yml.columns = self.parse_columns(self.scan_yml)
        self.scan_yml.mins_maxs_limit = self.get_int_optional(KEY_MINS_MAXS_LIMIT, 5)
        self.scan_yml.frequent_values_limit = self.get_int_optional(KEY_FREQUENT_VALUES_LIMIT, 5)
        self.scan_yml.samples_yml = self.parse_samples_yml(KEY_SAMPLES)

        # TODO change the next 2 properties to filter_tablesample (similar to samples.table_tablesample)
        # afaict, they are not docced and can be changed.
        self.scan_yml.sample_percentage = self.get_float_optional(KEY_SAMPLE_PERCENTAGE)
        self.scan_yml.sample_method = self.get_str_optional(KEY_SAMPLE_METHOD, 'SYSTEM').upper()

        filter = self.get_str_optional(KEY_FILTER)
        if filter:
            try:
                self.scan_yml.filter = filter
                self.scan_yml.filter_template = Template(filter)
            except Exception as e:
                self.error(f"Couldn't parse filter '{filter}': {str(e)}", KEY_FILTER)

        self.check_invalid_keys(VALID_SCAN_YML_KEYS)

    def parse_metrics(self):
        metrics: Set[str] = set(self.get_list_optional(KEY_METRICS, []))
        metrics_groups: Set[str] = set(self.get_list_optional(KEY_METRIC_GROUPS, []))

        self._push_context(metrics, KEY_METRICS)

        # Add special case for all
        if Metric.METRIC_GROUP_ALL in metrics_groups:
            metrics.update(Metric.METRIC_TYPES)
        else:
            for metric_group_name in Metric.METRIC_GROUPS:
                group_metrics = Metric.METRIC_GROUPS[metric_group_name]
                for metric in metrics:
                    if metric in group_metrics:
                        metrics_groups.add(metric_group_name)

            if Metric.METRIC_GROUP_VALIDITY in metrics_groups:
                metrics_groups.add(Metric.METRIC_GROUP_MISSING)

            if Metric.METRIC_GROUP_MISSING in metrics_groups:
                metrics.add(Metric.ROW_COUNT)

            for metric_group_name in metrics_groups:
                if metric_group_name in Metric.METRIC_GROUPS:
                    for group_metric in Metric.METRIC_GROUPS[metric_group_name]:
                        metrics.add(group_metric)
                else:
                    self.warning(f'Invalid metric_group {metric_group_name}')

            if Metric.HISTOGRAM in metrics:
                metrics.add(Metric.MIN)
                metrics.add(Metric.MAX)

        self.check_invalid_keys(Metric.METRIC_TYPES)

        self._pop_context()

        return metrics

    def ensure_metric(self,
                      metrics: Set[str],
                      metric: str,
                      dependent_metric: str,
                      column_name: str = None):
        if metric not in metrics:
            metrics.add(metric)
            column_message = f' on column {column_name}' if column_name else ''
            self.info(f'Added metric {metric} as dependency of {dependent_metric}{column_message}')

    def is_metric_category_enabled(self, metrics: Set[str], category: str, category_metrics: List[str]):
        if category in metrics:
            return True
        for category_metric in category_metrics:
            if category_metric in metrics:
                return True
        return False

    def resolve_category(self,
                         metrics: Set[str],
                         metrics_groups: List[str],
                         category: str,
                         category_metrics: List[str],
                         column_name: str = None):
        if self.is_metric_category_enabled(metrics, category, category_metrics):
            if category in metrics:
                metrics.remove(category)
            for category_metric in category_metrics:
                self.ensure_metric(metrics, category_metric, category, column_name)

    def remove_metric(self, metrics: Set[str], metric: str):
        """Returns True if the metric was removed from the set"""
        if metric in metrics:
            metrics.remove(metric)
            return True
        else:
            return False

    def parse_columns(self, scan_configuration: ScanYml) -> dict:
        columns_dict = self.get_dict_optional(KEY_COLUMNS, {})
        self._push_context(columns_dict, KEY_COLUMNS)

        scan_configuration_columns = {}

        for column_name in columns_dict:
            column_dict = columns_dict.get(column_name)
            if not isinstance(column_dict, dict):
                self.error(f'Column {column_name} should be an object, not a {type(column_dict)}', KEY_COLUMNS)
            else:
                self._push_context(column_dict, column_name)

                metrics: Set[str] = self.parse_metrics()

                if self.remove_metric(metrics, Metric.ROW_COUNT):
                    self.ensure_metric(scan_configuration.metrics, Metric.ROW_COUNT,
                                       f'{Metric.ROW_COUNT} {column_name}')

                missing = None
                if any(cfg in column_dict.keys() for cfg in COLUMN_MISSING_KEYS):
                    missing = Missing()
                    missing.values = column_dict.get(COLUMN_KEY_MISSING_VALUES)
                    missing.format = column_dict.get(COLUMN_KEY_MISSING_FORMAT)
                    missing.regex = column_dict.get(COLUMN_KEY_MISSING_REGEX)

                validity = None

                if any(cfg in column_dict.keys() for cfg in COLUMN_VALID_KEYS):
                    validity = Validity()
                    validity.format = column_dict.get(COLUMN_KEY_VALID_FORMAT)
                    if validity.format is not None and Validity.FORMATS.get(validity.format) is None:
                        self.warning(f'Invalid {column_name}.{COLUMN_KEY_VALID_FORMAT}: {validity.format}')
                    validity.regex = column_dict.get(COLUMN_KEY_VALID_REGEX)
                    validity.values = column_dict.get(COLUMN_KEY_VALID_VALUES)
                    validity.min = column_dict.get(COLUMN_KEY_VALID_MIN)
                    validity.max = column_dict.get(COLUMN_KEY_VALID_MAX)
                    validity.min_length = column_dict.get(COLUMN_KEY_VALID_MIN_LENGTH)
                    validity.max_length = column_dict.get(COLUMN_KEY_VALID_MAX_LENGTH)

                sql_metric_ymls = self.parse_sql_metric_ymls(metrics_key=COLUMN_KEY_SQL_METRICS,
                                                             column_name=column_name)

                tests = self.parse_tests(column_dict,
                                         COLUMN_KEY_TESTS,
                                         context_table_name=scan_configuration.table_name,
                                         context_column_name=column_name)

                samples_yml = self.parse_samples_yml(COLUMN_KEY_SAMPLES)
                if samples_yml and samples_yml.table_limit:
                    self.warning(f"Invalid column samples key 'table_limit'")
                if samples_yml and samples_yml.table_tablesample:
                    self.warning(f"Invalid column samples key 'table_tablesample'")

                self.check_invalid_keys(VALID_COLUMN_KEYS)

                column_name_lower = column_name.lower()
                scan_configuration_columns[column_name_lower] = ScanYmlColumn(
                    metrics=metrics,
                    sql_metric_ymls=sql_metric_ymls,
                    missing=missing,
                    validity=validity,
                    tests=tests,
                    samples_yml=samples_yml)

                self._pop_context()

        self._pop_context()

        return scan_configuration_columns

    def parse_sql_metric_ymls(self, metrics_key: str, column_name: Optional[str] = None) -> List[SqlMetricYml]:
        sql_metrics_dicts: List[dict] = self.get_list_optional(metrics_key, [])
        if isinstance(sql_metrics_dicts, list):
            self._push_context(sql_metrics_dicts, metrics_key)
            try:
                sql_metric_ymls = []
                for i in range(len(sql_metrics_dicts)):
                    sql_metric_dict = sql_metrics_dicts[i]
                    if isinstance(sql_metric_dict, dict):
                        metric_type = sql_metric_dict.get(SQL_METRIC_KEY_TYPE, 'numeric')
                        metric_group_fields = sql_metric_dict.get(SQL_METRIC_KEY_GROUP_FIELDS)
                        if metric_group_fields:
                            metric_type = 'numeric_groups'

                        self._push_context(object=sql_metric_dict, name=i)
                        try:
                            sql_metric_yml = None

                            if metric_type == 'failed_rows':
                                sql_metric_yml = self.parse_sql_metric_failed_rows(
                                    metric_type,
                                    sql_metric_index=i,
                                    column_name=column_name)

                            elif metric_type.startswith('numeric'):
                                sql_metric_yml = self.parse_sql_metric(
                                    sql_metric_dict=sql_metric_dict,
                                    sql_metric_type=metric_type,
                                    sql_metric_index=i,
                                    column_name=column_name)
                            else:
                                self.error(f'Unknown sql_metric type {metric_type}')

                            if sql_metric_yml:
                                sql_metric_ymls.append(sql_metric_yml)

                        finally:
                            self._pop_context()
                    else:
                        self.error(f'Invalid YAML: SQL metric {i} was {type(sql_metric_dict)}, expected object')

                return sql_metric_ymls
            finally:
                self._pop_context()
        elif sql_metrics_dicts is not None:
            self.error(
                f'Invalid YAML structure near {metrics_key}: Expected list of SQL metrics, but was {type(sql_metrics_dicts)}',
                metrics_key)

    def parse_sql_metric(self,
                         sql_metric_dict,
                         sql_metric_type: str,
                         sql_metric_index: int,
                         column_name: Optional[str] = None) -> Optional[SqlMetricYml]:
        sql_metric_name = self.get_str_optional(SQL_METRIC_KEY_NAME)
        metric_names = self.get_list_optional(SQL_METRIC_KEY_METRIC_NAMES)
        group_fields = self.get_list_optional(SQL_METRIC_KEY_GROUP_FIELDS)
        sql = self.get_str_optional(SQL_METRIC_KEY_SQL)
        sql_file = self.get_str_optional(SQL_METRIC_KEY_SQL_FILE)

        if not sql and not sql_file:
            self.error('No sql nor sql_file specified in SQL metric')
        elif sql_file:
            file_system = FileSystemSingleton.INSTANCE
            sql_file_path = file_system.join(file_system.dirname(self.scan_yaml_path), sql_file)
            sql = file_system.file_read_as_str(sql_file_path)

        tests = self.parse_tests(
            sql_metric_dict,
            SQL_METRIC_KEY_TESTS,
            context_table_name=self.scan_yml.table_name,
            context_column_name=column_name,
            context_sql_metric_name=sql_metric_name,
            context_sql_metric_index=sql_metric_index)

        sql_metric_title = ((column_name + '.' if column_name else '') +
                            (sql_metric_name if sql_metric_name else f'sql_metric[{sql_metric_index}]'))

        sql_metric_yml: SqlMetricYml = SqlMetricYml(type=sql_metric_type,
                                                    name=None,
                                                    title=sql_metric_title,
                                                    sql=sql,
                                                    index=sql_metric_index,
                                                    column_name=column_name,
                                                    metric_names=metric_names,
                                                    group_fields=group_fields,
                                                    tests=tests)

        self.check_invalid_keys(VALID_SQL_METRIC_KEYS)
        return sql_metric_yml

    def parse_sql_metric_failed_rows(self,
                                     sql_metric_type: str,
                                     sql_metric_index: int,
                                     column_name: str) -> Optional[SqlMetricYml]:

        sql_metric_name = self.get_str_required(SQL_METRIC_KEY_NAME)
        if sql_metric_name is None:
            return None

        # Only allow for valid python identifiers as the metric names in failed rows
        # TODO make this consistent with the other sql metric names
        if not re.match(r"^[^\d\W]\w*\Z$", sql_metric_name):
            self.error(f'Invalid metric identifier {sql_metric_name}', SQL_METRIC_KEY_NAME)
            return None

        test_name = sql_metric_name
        test_expression = f'{test_name} == 0'
        test_id = self.create_test_id(test_expression, test_name, sql_metric_index, column_name, sql_metric_name,
                                      sql_metric_index)
        test_title = self.create_test_title(test_expression, test_name, sql_metric_index, column_name, sql_metric_name,
                                            sql_metric_index)

        test = Test(id=test_id,
                    title=test_title,
                    expression=test_expression,
                    metrics=[sql_metric_name],
                    column=column_name)

        return SqlMetricYml(
            type=sql_metric_type,
            name=sql_metric_name,
            title=self.get_str_optional(SQL_METRIC_KEY_TITLE),
            sql=self.get_str_optional(SQL_METRIC_KEY_SQL),
            column_name=column_name,
            index=sql_metric_index,
            failed_limit=self.get_int_optional(SQL_METRIC_KEY_FAILED_LIMIT),
            tests=[test])

    def parse_samples_yml(self, samples_key: str) -> Optional[SamplesYml]:
        samples = self.get_dict_optional(samples_key)
        if samples is not None:
            self._push_context(samples, samples_key)
            try:
                samples_yml = SamplesYml(
                    table_limit=self.get_int_optional(SAMPLES_KEY_DATASET_LIMIT),
                    table_tablesample=self.get_str_optional(SAMPLES_KEY_DATASET_TABLESAMPLE),
                    failed_limit=self.get_int_optional(SAMPLES_KEY_FAILED_LIMIT),
                    failed_tablesample=self.get_str_optional(SAMPLES_KEY_FAILED_TABLESAMPLE),
                    passed_limit=self.get_int_optional(SAMPLES_KEY_PASSED_LIMIT),
                    passed_tablesample=self.get_str_optional(SAMPLES_KEY_PASSED_TABLESAMPLE)
                )
                return samples_yml
            finally:
                self._pop_context()
        pass
