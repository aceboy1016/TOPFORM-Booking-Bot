from unittest.mock import MagicMock
import pytest
from sheets_service import SheetsService, SheetsUnavailable

def sheet_with(rows):
    sheet=SheetsService();sheet._credentials=object()
    api=MagicMock()
    api.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value={'values':rows}
    sheet._get_fresh_service=lambda:api
    return sheet

def test_unregistered_customer_rows_do_not_disable_registered_users():
    sheet=sheet_with([['未登録','', '○'],['登録済み','test-user','○'],['氏名のみ']])
    assert [c['line_id'] for c in sheet.fetch_customer_master()]==['test-user']

@pytest.mark.parametrize('rows',[[['','test-user']],[['A','same-id'],['B','same-id']]])
def test_registered_rows_still_require_names_and_unique_ids(rows):
    with pytest.raises(SheetsUnavailable): sheet_with(rows).fetch_customer_master()
