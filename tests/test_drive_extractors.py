from __future__ import annotations

import io

from openpyxl import Workbook

from gdrive_rag_mcp.drive import GOOGLE_SHEET, GoogleDriveSource


def test_google_sheet_is_rendered_with_sheet_names_and_tabular_values() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Thuế VAT"
    sheet.append(["Mặt hàng", "Thuế suất"])
    sheet.append(["Sách", 5])
    buffer = io.BytesIO()
    workbook.save(buffer)

    text = GoogleDriveSource._extract(buffer.getvalue(), GOOGLE_SHEET)

    assert "# Sheet: Thuế VAT" in text
    assert "Mặt hàng\tThuế suất" in text
    assert "Sách\t5" in text
