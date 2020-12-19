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

import logging
from typing import List

from sodasql.scan.column import Column
from sodasql.scan.custom_metric import CustomMetric
from sodasql.scan.measurement import Measurement
from sodasql.scan.metric import Metric
from sodasql.scan.missing import Missing
from sodasql.scan.scan_configuration import ScanConfiguration
from sodasql.scan.scan_result import ScanResult
from sodasql.scan.test_result import TestResult
from sodasql.scan.validity import Validity
from sodasql.soda_client.soda_client import SodaClient
from sodasql.warehouse.dialect import Dialect
from sodasql.warehouse.warehouse import Warehouse


class Scan:

    def __init__(self,
                 warehouse: Warehouse,
                 scan_configuration: ScanConfiguration = None,
                 custom_metrics: List[CustomMetric] = None,
                 soda_client: SodaClient = None):
        self.soda_client: SodaClient = soda_client
        self.warehouse: Warehouse = warehouse
        self.dialect: Dialect = warehouse.dialect
        self.scan_configuration: ScanConfiguration = scan_configuration
        self.custom_metrics: List[CustomMetric] = custom_metrics

    def execute(self):
        assert self.warehouse.name, 'warehouse.name is required'
        assert self.scan_configuration.table_name, 'scan_configuration.table_name is required'
        scan_reference = {
            'warehouse': self.warehouse.name,
            'table_name': self.scan_configuration.table_name
        }

        measurements: List[Measurement] = []
        test_results: List[TestResult] = []

        columns: List[Column] = self.query_columns(self.scan_configuration)
        measurements.append(Measurement(Metric.SCHEMA, value=columns))
        if self.soda_client:
            self.soda_client.send_columns(scan_reference, columns)

        if self.scan_configuration:
            columns_aggregation_measurements: List[Measurement] = \
                self.query_aggregations(self.scan_configuration, columns)
            measurements.extend(columns_aggregation_measurements)

            if self.soda_client:
                self.soda_client.send_column_aggregation_measurements(scan_reference, columns_aggregation_measurements)

            test_results = self.run_tests(measurements, self.scan_configuration)

        return ScanResult(measurements, test_results)

    def query_columns(self, scan_configuration: ScanConfiguration) -> List[Column]:
        sql = self.warehouse.dialect.sql_columns_metadata_query(scan_configuration)
        column_tuples = self.warehouse.execute_query_all(sql)
        columns = []
        for column_tuple in column_tuples:
            name = column_tuple[0]
            type = column_tuple[1]
            nullable = 'YES' == column_tuple[2].upper()
            columns.append(Column(name, type, nullable))
        logging.debug(str(len(columns))+' columns:')
        for column in columns:
            logging.debug(f'  {column.name} {column.type} {"" if column.nullable else "not null"}')
        return columns

    def query_aggregations(
            self,
            scan_configuration: ScanConfiguration,
            columns: List[Column]) -> List[Measurement]:

        fields: List[str] = []
        measurements: List[Measurement] = []

        dialect = self.warehouse.dialect
        fields.append(dialect.sql_expr_count_all())
        measurements.append(Measurement(Metric.ROW_COUNT))

        # maps db column names to missing and invalid metric indices in the measurements
        # eg { 'colname': {'missing': 2, 'invalid': 3}, ...}
        column_metric_indices = {}

        for column in columns:
            metric_indices = {}
            column_metric_indices[column.name] = metric_indices

            quoted_column_name = dialect.qualify_column_name(column.name)

            missing = scan_configuration.get_missing(column)
            validity = scan_configuration.get_validity(column)

            is_valid_enabled = validity is not None \
                and scan_configuration.is_valid_enabled(column)

            is_missing_enabled = \
                is_valid_enabled \
                or scan_configuration.is_missing_enabled(column)

            missing_condition = self.get_missing_condition(column, missing)
            valid_condition = self.get_valid_condition(column, validity)

            non_missing_and_valid_condition = \
                f'NOT {missing_condition} AND {valid_condition}' if valid_condition else f'NOT {missing_condition}'

            if is_missing_enabled:
                metric_indices['missing'] = len(measurements)
                fields.append(f'{dialect.sql_expr_count_conditional(missing_condition)}')
                measurements.append(Measurement(Metric.MISSING_COUNT, column.name))

            if is_valid_enabled:
                metric_indices['valid'] = len(measurements)
                fields.append(f'{dialect.sql_expr_count_conditional(non_missing_and_valid_condition)}')
                measurements.append(Measurement(Metric.VALID_COUNT, column.name))

            if dialect.is_text(column):
                if scan_configuration.is_metric_enabled(column, Metric.MIN_LENGTH):
                    length_expr = dialect.sql_expr_conditional(
                        non_missing_and_valid_condition,
                        dialect.sql_expr_length(quoted_column_name))
                    fields.append(dialect.sql_expr_min(length_expr))
                    measurements.append(Measurement(Metric.MIN_LENGTH, column.name))

                if scan_configuration.is_metric_enabled(column, Metric.MAX_LENGTH):
                    length_expr = dialect.sql_expr_conditional(
                        non_missing_and_valid_condition,
                        dialect.sql_expr_length(quoted_column_name))
                    fields.append(dialect.sql_expr_max(length_expr))
                    measurements.append(Measurement(Metric.MAX_LENGTH, column.name))

                validity_format = scan_configuration.get_validity_format(column)
                is_column_numeric_text_format = isinstance(validity_format, str) and validity_format.startswith('number_')

                if is_column_numeric_text_format:
                    numeric_text_expr = dialect.sql_expr_conditional(
                        non_missing_and_valid_condition,
                        dialect.sql_expr_cast_text_to_number(quoted_column_name, validity_format))

                    if scan_configuration.is_metric_enabled(column, Metric.MIN):
                        fields.append(dialect.sql_expr_min(numeric_text_expr))
                        measurements.append(Measurement(Metric.MIN, column.name))

                    if scan_configuration.is_metric_enabled(column, Metric.MAX):
                        fields.append(dialect.sql_expr_max(numeric_text_expr))
                        measurements.append(Measurement(Metric.MAX, column.name))

                    if scan_configuration.is_metric_enabled(column, Metric.AVG):
                        fields.append(dialect.sql_expr_avg(numeric_text_expr))
                        measurements.append(Measurement(Metric.AVG, column.name))

                    if scan_configuration.is_metric_enabled(column, Metric.SUM):
                        fields.append(dialect.sql_expr_sum(numeric_text_expr))
                        measurements.append(Measurement(Metric.SUM, column.name))

        sql = 'SELECT \n  ' + ',\n  '.join(fields) + ' \n' \
              'FROM ' + dialect.qualify_table_name(scan_configuration.table_name)
        if scan_configuration.sample_size:
            sql += f'\nLIMIT {scan_configuration.sample_size}'

        query_result_tuple = self.warehouse.execute_query_one(sql)

        for i in range(0, len(measurements)):
            measurement = measurements[i]
            measurement.value = query_result_tuple[i]
            logging.debug(f'Query measurement: {measurement}')

        # Calculating derived measurements
        derived_measurements = []
        row_count = measurements[0].value
        for column in columns:
            metric_indices = column_metric_indices[column.name]
            missing_index = metric_indices.get('missing')
            if missing_index is not None:
                missing_count = measurements[missing_index].value
                missing_percentage = missing_count * 100 / row_count
                values_count = row_count - missing_count
                values_percentage = values_count * 100 / row_count
                derived_measurements.append(Measurement(Metric.MISSING_PERCENTAGE, column.name, missing_percentage))
                derived_measurements.append(Measurement(Metric.VALUES_COUNT, column.name, values_count))
                derived_measurements.append(Measurement(Metric.VALUES_PERCENTAGE, column.name, values_percentage))

                valid_index = metric_indices.get('valid')
                if valid_index is not None:
                    valid_count = measurements[valid_index].value
                    invalid_count = row_count - missing_count - valid_count
                    invalid_percentage = invalid_count * 100 / row_count
                    valid_percentage = valid_count * 100 / row_count
                    derived_measurements.append(Measurement(Metric.INVALID_PERCENTAGE, column.name, invalid_percentage))
                    derived_measurements.append(Measurement(Metric.INVALID_COUNT, column.name, invalid_count))
                    derived_measurements.append(Measurement(Metric.VALID_PERCENTAGE, column.name, valid_percentage))

        for derived_measurement in derived_measurements:
            logging.debug(f'Derived measurement: {derived_measurement}')

        measurements.extend(derived_measurements)

        return measurements

    def run_tests(self,
                  measurements: List[Measurement],
                  scan_configuration: ScanConfiguration):
        test_results = []
        if scan_configuration and scan_configuration.columns:
            for column_name in scan_configuration.columns:
                scan_configuration_column = scan_configuration.columns.get(column_name)
                if scan_configuration_column.tests:
                    column_measurement_values = {
                        measurement.metric: measurement.value
                        for measurement in measurements
                        if measurement.column == column_name
                    }
                    for test in scan_configuration_column.tests:
                        test_values = {metric: value for metric, value in column_measurement_values.items() if metric in test}
                        test_outcome = True if eval(test, test_values) else False
                        test_results.append(TestResult(test_outcome, test, test_values, column_name))
        return test_results

    def get_missing_condition(self, column: Column, missing: Missing):
        quoted_column_name = self.dialect.qualify_column_name(column.name)
        if missing is None:
            return f'{quoted_column_name} IS NULL'
        validity_clauses = [f'{quoted_column_name} IS NULL']
        if missing.values is not None:
            sql_expr_missing_values = self.dialect.sql_expr_list(column, missing.values)
            validity_clauses.append(f'{quoted_column_name} IN {sql_expr_missing_values}')
        if missing.format is not None:
            format_regex = Missing.FORMATS.get(missing.format)
            validity_clauses.append(self.dialect.sql_expr_regexp_like(quoted_column_name, format_regex))
        if missing.regex is not None:
            validity_clauses.append(self.dialect.sql_expr_regexp_like(quoted_column_name, missing.regex))
        return '(' + ' OR '.join(validity_clauses) + ')'

    def get_valid_condition(self, column: Column, validity: Validity):
        quoted_column_name = self.dialect.qualify_column_name(column.name)
        if validity is None:
            return None
        validity_clauses = []
        if validity.format:
            format_regex = Validity.FORMATS.get(validity.format)
            validity_clauses.append(self.dialect.sql_expr_regexp_like(quoted_column_name, format_regex))
        if validity.regex:
            validity_clauses.append(self.dialect.sql_expr_regexp_like(quoted_column_name, validity.regex))
        if validity.min_length:
            validity_clauses.append(f'{self.dialect.sql_expr_length(quoted_column_name)} >= {validity.min_length}')
        if validity.max_length:
            validity_clauses.append(f'{self.dialect.sql_expr_length(quoted_column_name)} <= {validity.max_length}')
        # TODO add min and max clauses
        return '(' + ' AND '.join(validity_clauses) + ')'