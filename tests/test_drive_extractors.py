from __future__ import annotations

import io
from types import SimpleNamespace

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


def test_drive_folder_names_are_optional_path_metadata() -> None:
    assert GoogleDriveSource._classify(("01-Orchestrator", "02-Finance", "03-Resources")) == {
        "ownerProfileId": "orchestrator",
        "businessFunction": "finance",
        "paraCategory": "resources",
    }
    assert GoogleDriveSource._classify(("orchestrator", "finance")) == {
        "ownerProfileId": "orchestrator",
        "businessFunction": "finance",
        "paraCategory": "",
    }
    assert GoogleDriveSource._classify(()) == {
        "ownerProfileId": "",
        "businessFunction": "",
        "paraCategory": "",
    }


def test_relative_folder_path_records_root_and_every_ancestor_id() -> None:
    source = object.__new__(GoogleDriveSource)
    source.settings = SimpleNamespace(folder_id="root-id")
    folders = {
        "business-id": {
            "name": "Finance",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": ["profile-id"],
        },
        "profile-id": {
            "name": "Orchestrator",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": ["root-id"],
        },
    }
    source._get_item = lambda folder_id: folders.get(folder_id)  # type: ignore[method-assign]

    assert source._relative_folder_path({"parents": ["business-id"]}) == (
        ("Orchestrator", "Finance"),
        ("root-id", "profile-id", "business-id"),
    )
