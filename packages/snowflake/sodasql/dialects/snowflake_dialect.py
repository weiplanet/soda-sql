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

from snowflake import connector
from snowflake.connector import errorcode
from snowflake.connector.network import DEFAULT_SOCKET_CONNECT_TIMEOUT

from sodasql.scan.dialect import Dialect, SNOWFLAKE, KEY_WAREHOUSE_TYPE, KEY_CONNECTION_TIMEOUT
from sodasql.scan.parser import Parser


class SnowflakeDialect(Dialect):

    def __init__(self, parser: Parser):
        super().__init__(SNOWFLAKE)
        if parser:
            self.account = parser.get_str_required_env('account')
            self.warehouse = parser.get_str_required_env('warehouse')
            self.username = parser.get_str_required_env('username')
            self.password = parser.get_credential('password')
            self.database = parser.get_str_optional_env('database')
            self.schema = parser.get_str_required_env('schema')
            self.role = parser.get_str_optional('role')
            self.passcode_in_password = parser.get_bool_optional('passcode_in_password', False)
            self.private_key = parser.get_str_optional('private_key')
            self.client_prefetch_threads = parser.get_int_optional('client_prefetch_threads', 4)
            self.client_session_keep_alive = parser.get_bool_optional('client_session_keep_alive', False)
            self.authenticator = parser.get_str_optional('authenticator', 'snowflake')
            self.connection_timeout = parser.get_int_optional(KEY_CONNECTION_TIMEOUT, DEFAULT_SOCKET_CONNECT_TIMEOUT)

    def default_connection_properties(self, params: dict):
        return {
            KEY_WAREHOUSE_TYPE: SNOWFLAKE,
            'username': 'env_var(SNOWFLAKE_USERNAME)',
            'password': 'env_var(SNOWFLAKE_PASSWORD)',
            'account': 'YOURACCOUNT.eu-central-1',
            'database': params.get('database', 'YOUR_DATABASE'),
            'warehouse': 'YOUR_WAREHOUSE',
            'schema': 'PUBLIC'
        }

    def default_env_vars(self, params: dict):
        return {
            'SNOWFLAKE_USERNAME': params.get('username', 'YOUR_SNOWFLAKE_USERNAME_GOES_HERE'),
            'SNOWFLAKE_PASSWORD': params.get('password', 'YOUR_SNOWFLAKE_PASSWORD_GOES_HERE')
        }

    def create_connection(self):
        try:
            conn = connector.connect(
                user=self.username,
                password=self.password,
                account=self.account,
                warehouse=self.warehouse,
                database=self.database,
                schema=self.schema,
                login_timeout=self.connection_timeout,
                role=self.role,
                passcode_in_password=self.passcode_in_password,
                private_key=self.private_key,
                client_prefetch_threads=self.client_prefetch_threads,
                client_session_keep_alive=self.client_session_keep_alive,
                authenticator=self.authenticator,
            )
            return conn

        except Exception as e:
            self.try_to_raise_soda_sql_exception(e)

    def is_text(self, column_type: str):
        return column_type.upper() in ['VARCHAR', 'CHAR', 'CHARACTER', 'STRING', 'TEXT']

    def is_number(self, column_type: str):
        return column_type.upper() in ['NUMBER', 'INT', 'INTEGER', 'BIGINT', 'SMALLINT', 'TINYINT', 'BYTEINT',
                                       'FLOAT', 'FLOAT4', 'FLOAT8',
                                       'DOUBLE', 'DOUBLE PRECISION', 'REAL']

    def is_time(self, column_type: str):
        return column_type.upper() in ['DATE', 'DATETIME', 'TIME', 'TIMESTAMP',
                                       'TIMESTAMP_LTZ', 'TIMESTAMP_NTZ', 'TIMESTAMP_TZ']

    def sql_tables_metadata_query(self, limit: str = 10, filter: str = None):
        sql = (f"SELECT table_name \n"
               f"FROM information_schema.tables \n"
               f"WHERE lower(table_schema)='{self.schema.lower()}'")
        if self.database:
            sql += f" \n  AND lower(table_catalog) = '{self.database.lower()}'"
        if isinstance(limit, int):
            sql += f" \nLIMIT {limit}"
        return sql

    def sql_columns_metadata_query(self, table_name: str) -> str:
        sql = (f"SELECT column_name, data_type, is_nullable \n"
               f'FROM information_schema.columns \n'
               f"WHERE lower(table_name) = '{table_name.lower()}'")
        if self.database:
            sql += f" \n  AND lower(table_catalog) = '{self.database.lower()}'"
        if self.schema:
            sql += f" \n  AND lower(table_schema) = '{self.schema.lower()}'"
        return sql

    def qualify_regex(self, regex) -> str:
        return self.escape_metacharacters(regex)

    def qualify_column_name(self, column_name: str):
        return f'"{column_name}"'

    def qualify_table_name(self, table_name: str) -> str:
        return f'"{table_name.upper()}"'

    def is_connection_error(self, exception):
        if exception is None or exception.errno is None:
            return False
        # unfortunately ER_FAILED_TO_CONNECT_TO_DB can't be used since it is mostly coming when auth is wrong
        return exception.errno == errorcode.ER_CONNECTION_IS_CLOSED or \
               exception.errno == errorcode.ER_FAILED_TO_REQUEST or \
               exception.errno == errorcode.ER_FAILED_TO_SERVER or \
               exception.errno == errorcode.ER_IDP_CONNECTION_ERROR or \
               exception.errno == errorcode.ER_INCORRECT_DESTINATION or \
               exception.errno == errorcode.ER_UNABLE_TO_OPEN_BROWSER or \
               exception.errno == errorcode.ER_UNABLE_TO_START_WEBSERVER or \
               exception.errno == errorcode.ER_INVALID_CERTIFICATE or \
               exception.errno == errorcode.ER_NO_ACCOUNT_NAME or \
               exception.errno == errorcode.ER_OLD_PYTHON or \
               exception.errno == errorcode.ER_NO_WINDOWS_SUPPORT or \
               exception.errno == errorcode.ER_FAILED_TO_GET_BOOTSTRAP or \
               exception.errno == errorcode.ER_NO_HOSTNAME_FOUND

    def is_authentication_error(self, exception):
        if exception is None or exception.errno is None:
            return False
        return exception.errno == errorcode.ER_FAILED_TO_CONNECT_TO_DB or \
               exception.errno == errorcode.ER_NO_USER or \
               exception.errno == errorcode.ER_NO_PASSWORD or \
               exception.errno == errorcode.ER_NOT_HTTPS_USED or \
               exception.errno == errorcode.ER_INVALID_VALUE or \
               exception.errno == errorcode.ER_INVALID_PRIVATE_KEY
