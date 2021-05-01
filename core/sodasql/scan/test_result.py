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
import json
from dataclasses import dataclass
from typing import Optional

from sodasql.common.json_helper import JsonHelper
from sodasql.scan.test import Test


@dataclass
class TestResult:

    test: Test
    passed: bool
    values: Optional[dict] = None
    error: Optional[Exception] = None
    group_values: Optional[dict] = None

    def __str__(self):
        return (f'Test {self.test.title} {"passed" if self.passed else "failed"}' +
                (f" with group values {self.group_values}" if self.group_values else '') +
                f' with measurements {json.dumps(JsonHelper.to_jsonnable(self.values))}')

    def to_json(self):
        if not self.test or not self.test.expression:
            return {
                'error': 'Invalid test result'
            }

        test_result_json = {
            'id': self.test.id,
            'title': self.test.title,
            'description': self.test.title, # for backwards compatibility
            'expression': self.test.expression
        }

        if self.test.column:
            test_result_json['columnName'] = self.test.column

        if self.error:
            test_result_json['error'] = str(self.error)
        else:
            test_result_json['passed'] = self.passed
            test_result_json['values'] = JsonHelper.to_jsonnable(self.values)

        if self.group_values:
            test_result_json['groupValues'] = JsonHelper.to_jsonnable(self.group_values)

        return test_result_json
