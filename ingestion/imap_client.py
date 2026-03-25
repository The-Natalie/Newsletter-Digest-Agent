from __future__ import annotations

from datetime import date, timedelta

from imapclient import IMAPClient

from config import settings

BATCH_SIZE = 50


class FolderNotFoundError(Exception):
    def __init__(self, folder: str, available: list[str]) -> None:
        self.folder = folder
        self.available = available

    def __str__(self) -> str:
        return (
            f"Folder '{self.folder}' was not found. "
            f"Available folders: {', '.join(self.available)}"
        )


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def fetch_emails(folder: str, date_start: date, date_end: date) -> list[bytes]:
    """Connect to IMAP, select folder (read-only), search by date range, return raw MIME bytes.

    Args:
        folder: IMAP folder name (exact string, case-sensitive on most servers).
        date_start: First day of the date range (inclusive).
        date_end: Last day of the date range (inclusive).

    Returns:
        List of raw MIME email bytes, capped at settings.max_emails_per_run.

    Raises:
        FolderNotFoundError: If the folder does not exist on the server.
    """
    with IMAPClient(settings.imap_host, port=settings.imap_port, ssl=True) as client:
        client.login(settings.imap_username, settings.imap_password)

        # Pre-check folder existence before selecting
        folders_raw = client.list_folders()
        folder_names = [str(f[2]) for f in folders_raw]
        if folder not in folder_names:
            raise FolderNotFoundError(folder, folder_names)

        client.select_folder(folder, readonly=True)

        # SINCE is inclusive; BEFORE is exclusive — add 1 day to include date_end
        uids = client.search(["SINCE", date_start, "BEFORE", date_end + timedelta(days=1)])

        # Cap total emails processed per run
        uids = uids[: settings.max_emails_per_run]

        if not uids:
            return []

        raw_messages: list[bytes] = []
        for batch in _chunks(uids, BATCH_SIZE):
            response = client.fetch(batch, ["BODY.PEEK[]"])
            for uid in batch:
                raw_messages.append(response[uid][b"BODY[]"])

        return raw_messages
