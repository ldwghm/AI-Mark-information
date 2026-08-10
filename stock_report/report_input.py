"""Input selection shared by morning and afternoon report senders."""

import json
from pathlib import Path


def load_json_input(local_path, remote_loader, remote_path):
    """Load an explicit local artifact, falling back only when it does not exist."""
    if local_path:
        path = Path(local_path)
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    return remote_loader(remote_path)
