from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Settings
from .exceptions import ConfigError, ProcessingError


@dataclass(frozen=True)
class ManagementRow:
    row_number: int
    values: dict[str, str]

    def value(self, column_name: str) -> str | None:
        value = self.values.get(column_name)
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def source_type(self, settings: Settings) -> str:
        raw_value = self.value(settings.form_input_type_column)
        if not raw_value:
            raise ProcessingError(
                f"Missing source type column value: {settings.form_input_type_column}"
            )
        normalized = raw_value.strip().lower()
        aliases = {
            "url": "url",
            "動画url": "url",
            "動画 url": "url",
            "jw.org url": "url",
            "text": "text",
            "本文": "text",
            "テキスト": "text",
            "audio": "audio",
            "音声": "audio",
            "音声ファイル": "audio",
        }
        source_type = aliases.get(normalized)
        if not source_type:
            raise ProcessingError(f"Unsupported source type: {raw_value}")
        return source_type

    def tags(self, settings: Settings) -> list[str]:
        raw_value = self.value(settings.form_tags_column)
        if not raw_value:
            return []
        return [tag.strip().lstrip("#") for tag in raw_value.split(",") if tag.strip()]


class SheetsClient:
    def __init__(self, settings: Settings, service: Any | None = None):
        self._settings = settings
        self._service = service

    def get_row(self, spreadsheet_id: str, row_id: str) -> ManagementRow:
        rows = self._values(spreadsheet_id)
        if not rows:
            raise ProcessingError("Spreadsheet has no rows.")

        headers = [str(value).strip() for value in rows[0]]
        row_id_index = self._column_index(headers, self._settings.sheet_row_id_column)
        for index, row in enumerate(rows[1:], start=2):
            if row_id_index < len(row) and str(row[row_id_index]).strip() == row_id:
                values = {
                    header: str(row[column_index]).strip()
                    for column_index, header in enumerate(headers)
                    if header and column_index < len(row)
                }
                return ManagementRow(row_number=index, values=values)
        raise ProcessingError(f"row_id not found in spreadsheet: {row_id}")

    def update_success(
        self,
        spreadsheet_id: str,
        row_number: int,
        *,
        github_url: str | None,
        finished_at: str,
    ) -> None:
        headers = [str(value).strip() for value in self._values(spreadsheet_id)[0]]
        updates = {
            self._settings.sheet_status_column: "done",
            self._settings.sheet_github_url_column: github_url or "",
            self._settings.sheet_finished_at_column: finished_at,
            self._settings.sheet_error_column: "",
        }
        data = []
        for column_name, value in updates.items():
            column_index = self._column_index(headers, column_name)
            data.append(
                {
                    "range": (
                        f"{self._sheet_range_prefix(spreadsheet_id)}!"
                        f"{_column_letter(column_index + 1)}{row_number}"
                    ),
                    "values": [[value]],
                }
            )
        (
            self._build_service()
            .spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data},
            )
            .execute()
        )

    def _values(self, spreadsheet_id: str) -> list[list[Any]]:
        result = (
            self._build_service()
            .spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=self._sheet_range_prefix(spreadsheet_id))
            .execute()
        )
        return result.get("values", [])

    def _sheet_range_prefix(self, spreadsheet_id: str) -> str:
        title = self._settings.sheets_worksheet_name or self._first_sheet_title(
            spreadsheet_id
        )
        return _quote_sheet_name(title)

    def _first_sheet_title(self, spreadsheet_id: str) -> str:
        spreadsheet = (
            self._build_service()
            .spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets.properties.title")
            .execute()
        )
        sheets = spreadsheet.get("sheets", [])
        try:
            return sheets[0]["properties"]["title"]
        except (IndexError, KeyError) as exc:
            raise ProcessingError("Spreadsheet has no worksheet.") from exc

    def _build_service(self):
        if self._service is None:
            try:
                from googleapiclient.discovery import build
            except ImportError as exc:
                raise ConfigError(
                    "google-api-python-client is required for Sheets access."
                ) from exc
            self._service = build("sheets", "v4", cache_discovery=False)
        return self._service

    @staticmethod
    def _column_index(headers: list[str], column_name: str) -> int:
        try:
            return headers.index(column_name)
        except ValueError as exc:
            raise ProcessingError(f"Missing spreadsheet column: {column_name}") from exc


def _quote_sheet_name(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _column_letter(number: int) -> str:
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
