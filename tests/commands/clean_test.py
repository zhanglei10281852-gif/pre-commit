from __future__ import annotations

import contextlib
import os.path
from unittest import mock

import pytest

from pre_commit.commands.clean import clean


@pytest.fixture(autouse=True)
def fake_old_dir(tempdir_factory):
    fake_old_dir = tempdir_factory.get()

    def _expanduser(path, *args, **kwargs):
        assert path == '~/.pre-commit'
        return fake_old_dir

    with mock.patch.object(os.path, 'expanduser', side_effect=_expanduser):
        yield fake_old_dir


def test_clean(store, fake_old_dir):
    assert os.path.exists(fake_old_dir)
    assert os.path.exists(store.directory)
    clean(store)
    assert not os.path.exists(fake_old_dir)
    assert not os.path.exists(store.directory)


def test_clean_idempotent(store):
    clean(store)
    assert not os.path.exists(store.directory)
    clean(store)
    assert not os.path.exists(store.directory)


def test_clean_outputs_removed_and_deferred(store, cap_out):
    busy = os.path.join(store.directory, 'repobusy1')
    free = os.path.join(store.directory, 'repofree1')
    os.makedirs(busy)
    os.makedirs(free)

    hold = contextlib.ExitStack()
    store._hold_marker(hold, 'repobusy1')
    try:
        assert not clean(store)
    finally:
        hold.close()

    out = cap_out.get()
    assert f'Cleaned {free}.' in out
    assert os.path.exists(busy)
    assert not os.path.exists(free)
    assert 'is in use by another process -- skipped.' in out
    # the deferred resource must be distinguishable from removed ones
    assert f'Cleaned {busy}.' not in out

    # after the holder exits, a follow-up run completes the clean
    assert not clean(store)
    assert not os.path.exists(store.directory)


def test_clean_full_wipe_when_idle(store, cap_out):
    assert not clean(store)
    assert cap_out.get().splitlines()[-1] == (
        f'Cleaned {store.directory}.'
    )
