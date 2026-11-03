from __future__ import annotations

import contextlib
import logging
import os
import os.path
import shlex
import sqlite3
import stat
import subprocess
import sys
import time
from unittest import mock

import pytest

import pre_commit.constants as C
from pre_commit import git
from pre_commit.commands.gc import _gc
from pre_commit.store import _ACTIVE_DIRNAME
from pre_commit.store import _get_default_directory
from pre_commit.store import _LOCAL_RESOURCES
from pre_commit.store import _SESSION_NAME
from pre_commit.store import Store
from pre_commit.util import CalledProcessError
from pre_commit.util import cmd_output
from testing.fixtures import git_dir
from testing.util import git_commit
from testing.util import xfailif_windows


def _select_all_configs(store: Store) -> list[str]:
    with store.connect() as db:
        rows = db.execute('SELECT * FROM configs').fetchall()
        return [path for path, in rows]


def _select_all_repos(store: Store) -> list[tuple[str, str, str]]:
    with store.connect() as db:
        return db.execute('SELECT repo, ref, path FROM repos').fetchall()


def test_our_session_fixture_works():
    """There's a session fixture which makes `Store` invariantly raise to
    prevent writing to the home directory.
    """
    with pytest.raises(AssertionError):
        Store()


def test_get_default_directory_defaults_to_home():
    # Not we use the module level one which is not mocked
    ret = _get_default_directory()
    expected = os.path.realpath(os.path.expanduser('~/.cache/pre-commit'))
    assert ret == expected


def test_adheres_to_xdg_specification():
    with mock.patch.dict(
        os.environ, {'XDG_CACHE_HOME': '/tmp/fakehome'},
    ):
        ret = _get_default_directory()
    expected = os.path.realpath('/tmp/fakehome/pre-commit')
    assert ret == expected


def test_uses_environment_variable_when_present():
    with mock.patch.dict(
        os.environ, {'PRE_COMMIT_HOME': '/tmp/pre_commit_home'},
    ):
        ret = _get_default_directory()
    expected = os.path.realpath('/tmp/pre_commit_home')
    assert ret == expected


def test_store_init(store):
    # Should create the store directory
    assert os.path.exists(store.directory)
    # Should create a README file indicating what the directory is about
    with open(os.path.join(store.directory, 'README')) as readme_file:
        readme_contents = readme_file.read()
        for text_line in (
            'This directory is maintained by the pre-commit project.',
            'Learn more: https://github.com/pre-commit/pre-commit',
        ):
            assert text_line in readme_contents


def test_clone(store, tempdir_factory, caplog):
    path = git_dir(tempdir_factory)
    with contextlib.chdir(path):
        git_commit()
        rev = git.head_rev(path)
        git_commit()

    ret = store.clone(path, rev)
    # Should have printed some stuff
    assert caplog.record_tuples[0][-1].startswith(
        'Initializing environment for ',
    )

    # Should return a directory inside of the store
    assert os.path.exists(ret)
    assert ret.startswith(store.directory)
    # Directory should start with `repo`
    _, dirname = os.path.split(ret)
    assert dirname.startswith('repo')
    # Should be checked out to the rev we specified
    assert git.head_rev(ret) == rev

    # Assert there's an entry in the sqlite db for this
    assert _select_all_repos(store) == [(path, rev, ret)]


def test_warning_for_deprecated_stages_on_init(store, tempdir_factory, caplog):
    manifest = '''\
-   id: hook1
    name: hook1
    language: system
    entry: echo hook1
    stages: [commit, push]
-   id: hook2
    name: hook2
    language: system
    entry: echo hook2
    stages: [push, merge-commit]
'''

    path = git_dir(tempdir_factory)
    with open(os.path.join(path, C.MANIFEST_FILE), 'w') as f:
        f.write(manifest)
    cmd_output('git', 'add', '.', cwd=path)
    git_commit(cwd=path)
    rev = git.head_rev(path)

    store.clone(path, rev)
    assert caplog.record_tuples[1] == (
        'pre_commit',
        logging.WARNING,
        f'repo `{path}` uses deprecated stage names '
        f'(commit, push, merge-commit) which will be removed in a future '
        f'version.  '
        f'Hint: often `pre-commit autoupdate --repo {shlex.quote(path)}` '
        f'will fix this.  '
        f'if it does not -- consider reporting an issue to that repo.',
    )

    # should not re-warn
    caplog.clear()
    store.clone(path, rev)
    assert caplog.record_tuples == []


def test_no_warning_for_non_deprecated_stages_on_init(
        store, tempdir_factory, caplog,
):
    manifest = '''\
-   id: hook1
    name: hook1
    language: system
    entry: echo hook1
    stages: [pre-commit, pre-push]
-   id: hook2
    name: hook2
    language: system
    entry: echo hook2
    stages: [pre-push, pre-merge-commit]
'''

    path = git_dir(tempdir_factory)
    with open(os.path.join(path, C.MANIFEST_FILE), 'w') as f:
        f.write(manifest)
    cmd_output('git', 'add', '.', cwd=path)
    git_commit(cwd=path)
    rev = git.head_rev(path)

    store.clone(path, rev)
    assert logging.WARNING not in {tup[1] for tup in caplog.record_tuples}


def test_clone_cleans_up_on_checkout_failure(store):
    with pytest.raises(Exception) as excinfo:
        # This raises an exception because you can't clone something that
        # doesn't exist!
        store.clone('/i_dont_exist_lol', 'fake_rev')
    assert '/i_dont_exist_lol' in str(excinfo.value)

    repo_dirs = [
        d for d in os.listdir(store.directory) if d.startswith('repo')
    ]
    assert repo_dirs == []


def test_clone_when_repo_already_exists(store):
    # Create an entry in the sqlite db that makes it look like the repo has
    # been cloned.
    with sqlite3.connect(store.db_path) as db:
        db.execute(
            'INSERT INTO repos (repo, ref, path) '
            'VALUES ("fake_repo", "fake_ref", "fake_path")',
        )

    assert store.clone('fake_repo', 'fake_ref') == 'fake_path'


def test_clone_shallow_failure_fallback_to_complete(
    store, tempdir_factory,
    caplog,
):
    path = git_dir(tempdir_factory)
    with contextlib.chdir(path):
        git_commit()
        rev = git.head_rev(path)
        git_commit()

    # Force shallow clone failure
    def fake_shallow_clone(self, *args, **kwargs):
        raise CalledProcessError(1, (), b'', None)
    store._shallow_clone = fake_shallow_clone

    ret = store.clone(path, rev)

    # Should have printed some stuff
    assert caplog.record_tuples[0][-1].startswith(
        'Initializing environment for ',
    )

    # Should return a directory inside of the store
    assert os.path.exists(ret)
    assert ret.startswith(store.directory)
    # Directory should start with `repo`
    _, dirname = os.path.split(ret)
    assert dirname.startswith('repo')
    # Should be checked out to the rev we specified
    assert git.head_rev(ret) == rev

    # Assert there's an entry in the sqlite db for this
    assert _select_all_repos(store) == [(path, rev, ret)]


def test_clone_tag_not_on_mainline(store, tempdir_factory):
    path = git_dir(tempdir_factory)
    with contextlib.chdir(path):
        git_commit()
        cmd_output('git', 'checkout', 'master', '-b', 'branch')
        git_commit()
        cmd_output('git', 'tag', 'v1')
        cmd_output('git', 'checkout', 'master')
        cmd_output('git', 'branch', '-D', 'branch')

    # previously crashed on unreachable refs
    store.clone(path, 'v1')


def test_create_when_directory_exists_but_not_db(store):
    # In versions <= 0.3.5, there was no sqlite db causing a need for
    # backward compatibility
    os.remove(store.db_path)
    store = Store(store.directory)
    assert os.path.exists(store.db_path)


def test_create_when_store_already_exists(store):
    # an assertion that this is idempotent and does not crash
    Store(store.directory)


def test_db_repo_name(store):
    assert store.db_repo_name('repo', ()) == 'repo'
    assert store.db_repo_name('repo', ('b', 'a', 'c')) == 'repo:b,a,c'


def test_local_resources_reflects_reality():
    on_disk = {
        res.removeprefix('empty_template_')
        for res in os.listdir('pre_commit/resources')
        if res.startswith('empty_template_')
    }
    assert on_disk == {os.path.basename(x) for x in _LOCAL_RESOURCES}


def test_mark_config_as_used(store, tmpdir):
    with tmpdir.as_cwd():
        f = tmpdir.join('f').ensure()
        store.mark_config_used('f')
        assert _select_all_configs(store) == [f.strpath]


def test_mark_config_as_used_idempotent(store, tmpdir):
    test_mark_config_as_used(store, tmpdir)
    test_mark_config_as_used(store, tmpdir)


def test_mark_config_as_used_does_not_exist(store):
    store.mark_config_used('f')
    assert _select_all_configs(store) == []


def test_mark_config_as_used_roll_forward(store, tmpdir):
    with store.connect() as db:  # simulate pre-1.14.0
        db.executescript('DROP TABLE configs')
    test_mark_config_as_used(store, tmpdir)


@xfailif_windows  # pragma: win32 no cover
def test_mark_config_as_used_readonly(tmpdir):
    cfg = tmpdir.join('f').ensure()
    store_dir = tmpdir.join('store')
    # make a store, then we'll convert its directory to be readonly
    assert not Store(str(store_dir)).readonly  # directory didn't exist
    assert not Store(str(store_dir)).readonly  # directory did exist

    def _chmod_minus_w(p):
        st = os.stat(p)
        os.chmod(p, st.st_mode & ~(stat.S_IWUSR | stat.S_IWOTH | stat.S_IWGRP))

    _chmod_minus_w(store_dir)
    for fname in os.listdir(store_dir):
        assert not os.path.isdir(fname)
        _chmod_minus_w(os.path.join(store_dir, fname))

    store = Store(str(store_dir))
    assert store.readonly
    # should be skipped due to readonly
    store.mark_config_used(str(cfg))
    assert _select_all_configs(store) == []


def _active_dir(store: Store) -> str:
    return os.path.join(store.directory, _ACTIVE_DIRNAME)


def _marker_groups(store: Store) -> list[str]:
    if not os.path.exists(_active_dir(store)):
        return []
    return os.listdir(_active_dir(store))


def _make_clone_repo(tempdir_factory) -> tuple[str, str]:
    path = git_dir(tempdir_factory)
    with contextlib.chdir(path):
        git_commit()
        rev = git.head_rev(path)
    return path, rev


def test_active_creates_and_releases_session_marker(store):
    assert not os.path.exists(_active_dir(store))
    with store.active():
        assert _marker_groups(store) == [_SESSION_NAME]
    assert not os.path.exists(_active_dir(store))


def test_active_is_reentrant(store):
    with store.active():
        with store.active():
            assert _marker_groups(store) == [_SESSION_NAME]
        # the outer session is still active
        assert _marker_groups(store) == [_SESSION_NAME]
    assert not os.path.exists(_active_dir(store))


def test_active_marker_released_on_exception(store):
    with pytest.raises(RuntimeError):
        with store.active():
            raise RuntimeError('boom')
    assert not os.path.exists(_active_dir(store))


def test_active_marker_released_on_keyboard_interrupt(store):
    with pytest.raises(KeyboardInterrupt):
        with store.active():
            raise KeyboardInterrupt
    assert not os.path.exists(_active_dir(store))


def test_clone_within_active_is_marked_and_deduplicated(
        store, tempdir_factory,
):
    path, rev = _make_clone_repo(tempdir_factory)

    with store.active():
        cloned = store.clone(path, rev)
        name = os.path.basename(cloned)
        # the resource is marked active for the duration of the command
        assert name in _marker_groups(store)
        group = os.path.join(_active_dir(store), name)
        # exactly one marker regardless of how many hooks resolve it
        assert len(os.listdir(group)) == 1
        store.clone(path, rev)
        store.clone(path, rev)
        assert len(os.listdir(group)) == 1

    # released on normal exit -- no permanent activity left behind
    assert not os.path.exists(_active_dir(store))


def test_clone_without_active_does_not_leave_marker(
        store, tempdir_factory,
):
    path, rev = _make_clone_repo(tempdir_factory)
    store.clone(path, rev)
    assert not os.path.exists(_active_dir(store))


def test_failed_clone_releases_its_marker(store, tempdir_factory):
    with pytest.raises(Exception):
        with store.active():
            store.clone('/i_dont_exist_lol', 'fake_rev')
    # the failed clone directory and its marker are both gone
    assert not os.path.exists(_active_dir(store))
    assert [
        d for d in os.listdir(store.directory) if d.startswith('repo')
    ] == []


def test_scan_active_prunes_stale_markers(store):
    # a process which died (normally or after being killed) leaves the
    # marker file behind but no lock -- it must be reclaimed
    group = os.path.join(_active_dir(store), 'repodeadbeef')
    os.makedirs(group)
    with open(os.path.join(group, '1234-stale'), 'w') as f:
        f.write('pid: 1234\n')

    assert store._scan_active() == set()
    assert not os.path.exists(group)


def test_scan_active_finds_live_marker(store):
    name = 'repoalive12'
    stack = contextlib.ExitStack()
    store._hold_marker(stack, name)
    try:
        assert store._scan_active() == {name}
    finally:
        stack.close()
    assert store._scan_active() == set()


def test_clean_skips_active_resource_and_finishes_later(store):
    busy = os.path.join(store.directory, 'repobusy0001')
    os.makedirs(busy)
    hold = contextlib.ExitStack()
    store._hold_marker(hold, 'repobusy0001')
    try:
        free = os.path.join(store.directory, 'repofree00001')
        os.makedirs(free)

        removed, deferred = store.clean()
        # the free resource is deleted, the busy one is reported deferred
        assert free in removed
        assert deferred == [busy]
        assert os.path.exists(busy)
        assert not os.path.exists(free)
        # coordination state is preserved while anything is active
        assert os.path.exists(store.directory)
        assert os.path.exists(store.db_path)
    finally:
        hold.close()

    # once released, a later clean deterministically empties the store
    removed, deferred = store.clean()
    assert removed == [store.directory]
    assert deferred == []
    assert not os.path.exists(store.directory)


def test_clean_while_session_active_keeps_scratch_and_coordination(store):
    scratch = os.path.join(store.directory, 'patch1234-5678')
    free_repo = os.path.join(store.directory, 'repoold00001')
    with store.active():
        open(scratch, 'w').close()
        os.makedirs(free_repo)

        removed, deferred = store.clean()
        # unreferenced cached resources are still reclaimed mid-session
        assert free_repo in removed
        assert not os.path.exists(free_repo)
        # scratch files and coordination state survive an active session
        assert os.path.exists(scratch)
        assert os.path.exists(store.db_path)

    assert not os.path.exists(_active_dir(store))


def test_clean_defers_resources_while_global_lock_is_held(store):
    free = os.path.join(store.directory, 'repoother00')
    os.makedirs(free)

    # a clone / environment install / gc holding the global lock means no
    # cache resource is reclaimed in this pass -- clean never blocks on it
    with store.exclusive_lock():
        removed, deferred = store.clean()
    assert removed == []
    assert deferred == [free]
    assert os.path.exists(free)

    # a follow-up clean with no operation in progress fully converges
    removed, deferred = store.clean()
    assert removed == [store.directory]
    assert deferred == []


def test_active_resolution_takes_global_lock(store, tempdir_factory):
    # resolving an already cloned resource inside an activity is atomic
    # with respect to gc/clean (lock acquired + marker registered)
    path, rev = _make_clone_repo(tempdir_factory)
    cloned = store.clone(path, rev)
    with store.active():
        with store.exclusive_lock():
            pass  # the resolution must not hold a lingering lock
        resolved = store.clone(path, rev)
        assert resolved == cloned
        assert os.path.basename(cloned) in _marker_groups(store)


def test_clean_removes_db_row_for_deleted_resource(store):
    path = os.path.join(store.directory, 'repoorphan001')
    os.makedirs(path)
    with store.connect() as db:
        db.execute(
            'INSERT INTO repos (repo, ref, path) VALUES (?, ?, ?)',
            ('orphan', 'ref', path),
        )

    removed, deferred = store.clean()
    assert removed == [store.directory]
    assert not os.path.exists(store.directory)


# ---------------------------------------------------------------------------
# cross-process tests


_HOLDER_SCRIPT = """
import os, sys, time
from pre_commit.store import Store
home, repo, rev, ready, go = sys.argv[1:6]
store = Store(home)
with store.active():
    store.clone(repo, rev)
    open(ready, 'w').close()
    while not os.path.exists(go):
        time.sleep(0.01)
"""


def _spawn_repo_holder(tmp_path, repo, rev):
    home = str(tmp_path / 'home')
    os.makedirs(home)
    ready = str(tmp_path / 'ready')
    go = str(tmp_path / 'go')
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, PYTHONPATH=root)
    proc = subprocess.Popen(
        (sys.executable, '-c', _HOLDER_SCRIPT, home, repo, rev, ready, go),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 120
    while not os.path.exists(ready):
        assert proc.poll() is None, proc.stderr.read().decode()
        assert time.monotonic() < deadline
        time.sleep(0.02)
    return proc, home, go


def _list_repo_dirs(home: str) -> list[str]:
    if not os.path.exists(home):
        return []
    return [
        name for name in os.listdir(home)
        if os.path.isdir(os.path.join(home, name)) and name.startswith('repo')
    ]


def test_concurrent_clean_defers_active_process_resources(
        tmp_path, tempdir_factory,
):
    repo, rev = _make_clone_repo(tempdir_factory)
    proc, home, go = _spawn_repo_holder(tmp_path, repo, rev)
    try:
        # a concurrent clean cannot remove the in-use clone
        removed, deferred = Store(home).clean()
        assert removed == []
        assert len(deferred) == 1
        assert os.path.exists(deferred[0])
        assert len(_list_repo_dirs(home)) == 1
        # the coordination state is left untouched for the other process
        assert os.path.exists(os.path.join(home, 'db.db'))
    finally:
        open(go, 'w').close()
        assert proc.wait() == 0

    # after the process exits, a follow-up clean fully converges
    removed, deferred = Store(home).clean()
    assert removed == [home]
    assert deferred == []
    assert not os.path.exists(home)


def test_concurrent_gc_defers_active_process_resources(
        tmp_path, tempdir_factory,
):
    repo, rev = _make_clone_repo(tempdir_factory)
    proc, home, go = _spawn_repo_holder(tmp_path, repo, rev)
    try:
        # the clone is unreferenced by any registered config, so it would
        # be gc-able -- but it is in active use
        removed, in_use = _gc(Store(home))
        assert (removed, in_use) == (0, 1)
        assert len(_list_repo_dirs(home)) == 1
    finally:
        open(go, 'w').close()
        assert proc.wait() == 0

    # once released, gc removes it deterministically
    store = Store(home)
    removed, in_use = _gc(store)
    assert (removed, in_use) == (1, 0)
    assert _list_repo_dirs(home) == []


def test_clean_reclaims_resources_from_killed_process(
        tmp_path, tempdir_factory,
):
    repo, rev = _make_clone_repo(tempdir_factory)
    proc, home, _go = _spawn_repo_holder(tmp_path, repo, rev)
    try:
        proc.kill()
        assert proc.wait() == -15 or proc.returncode is not None
        # wait for the operating system to release the locks
        deadline = time.monotonic() + 30
        while Store(home).clean()[0] != [home] and time.monotonic() < deadline:
            time.sleep(0.05)
        # stale markers are identified and the store is fully reclaimed
        removed, deferred = Store(home).clean()
        assert removed == [home]
        assert deferred == []
        assert not os.path.exists(home)
    finally:
        if proc.poll() is None:  # pragma: no cover
            proc.kill()


def test_clone_with_recursive_submodules(store, tmp_path):
    sub = tmp_path.joinpath('sub')
    sub.mkdir()
    sub.joinpath('submodule').write_text('i am a submodule')
    cmd_output('git', '-C', str(sub), 'init', '.')
    cmd_output('git', '-C', str(sub), 'add', '.')
    git.commit(str(sub))

    repo = tmp_path.joinpath('repo')
    repo.mkdir()
    repo.joinpath('repository').write_text('i am a repo')
    cmd_output('git', '-C', str(repo), 'init', '.')
    cmd_output('git', '-C', str(repo), 'add', '.')
    cmd_output('git', '-C', str(repo), 'submodule', 'add', str(sub), 'sub')
    git.commit(str(repo))

    rev = git.head_rev(str(repo))
    ret = store.clone(str(repo), rev)

    assert os.path.exists(ret)
    assert os.path.exists(os.path.join(ret, str(repo), 'repository'))
    assert os.path.exists(os.path.join(ret, str(sub), 'submodule'))
