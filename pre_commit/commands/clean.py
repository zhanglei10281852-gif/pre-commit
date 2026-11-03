from __future__ import annotations

import os.path

from pre_commit import output
from pre_commit.store import Store
from pre_commit.util import rmtree


def clean(store: Store) -> int:
    legacy_path = os.path.expanduser('~/.pre-commit')
    if os.path.exists(legacy_path):
        rmtree(legacy_path)
        output.write_line(f'Cleaned {legacy_path}.')

    removed, in_use = store.clean()

    for directory in removed:
        output.write_line(f'Cleaned {directory}.')
    for directory in in_use:
        output.write_line(
            f'{directory} is in use by another process -- skipped.\n'
            f'Run `pre-commit clean` again once the process finishes.',
        )

    return 0
