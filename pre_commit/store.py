from __future__ import annotations

import contextlib
import logging
import os
import os.path
import sqlite3
import tempfile
import uuid
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Sequence

import pre_commit.constants as C
from pre_commit import clientlib
from pre_commit import file_lock
from pre_commit import git
from pre_commit.util import CalledProcessError
from pre_commit.util import clean_path_on_failure
from pre_commit.util import cmd_output_b
from pre_commit.util import resource_text
from pre_commit.util import rmtree


logger = logging.getLogger('pre_commit')


def _get_default_directory() -> str:
    """Returns the default directory for the Store.  This is intentionally
    underscored to indicate that `Store.get_default_directory` is the intended
    way to get this information.  This is also done so
    `Store.get_default_directory` can be mocked in tests and
    `_get_default_directory` can be tested.
    """
    ret = os.environ.get('PRE_COMMIT_HOME') or os.path.join(
        os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'),
        'pre-commit',
    )
    return os.path.realpath(ret)


_LOCAL_RESOURCES = (
    'Cargo.toml', 'main.go', 'go.mod', 'main.rs',
    'pre-commit-package-dev-1.rockspec',
    'pre_commit_placeholder_package.gemspec', 'setup.py',
    'environment.yml', 'Makefile.PL', 'pubspec.yaml',
    'renv.lock', 'renv/activate.R', 'renv/LICENSE.renv',
)

# Cache resources are marked "active" (in use by a live process) using os
# locked marker files living underneath this directory.  `clean` and `gc`
# never delete a resource which has a live marker and instead leave it for
# a later maintenance run.  Locks are released by the operating system when
# a process exits, however abruptly, so marker files whose lock can be
# acquired are stale and safely reclaimed.
_ACTIVE_DIRNAME = 'active'
# Marker for the store as a whole (protects db and scratch files such as
# stash patches for the duration of a command).  Never collides with a
# resource name, which always starts with `repo`.
_SESSION_NAME = '_session'
# Coordination state which is only removed when nothing is active.
_COORDINATION = frozenset(('README', 'db.db', '.lock', _ACTIVE_DIRNAME))


def _remove_marker(filename: str) -> None:
    # the caller releases the lock before running this callback, so the
    # file is closed and safe to remove (required on windows)
    with contextlib.suppress(OSError):
        os.unlink(filename)
    group = os.path.dirname(filename)
    with contextlib.suppress(OSError):
        os.rmdir(group)
    with contextlib.suppress(OSError):
        os.rmdir(os.path.dirname(group))


class _Activity:
    """The resources held by one process for the duration of a command.

    A resource is registered at most once -- several hooks sharing a clone
    or a clone reused both for its manifest and its environments produce a
    single marker.
    """

    def __init__(self, store: Store) -> None:
        self._store = store
        self._stack = contextlib.ExitStack()
        self._held: set[str] = set()

    def hold_name(self, name: str) -> None:
        if name not in self._held:
            self._store._hold_marker(self._stack, name)
            self._held.add(name)

    def hold_path(self, path: str) -> None:
        name = self._store._resource_name(path)
        if name is not None:
            self.hold_name(name)

    def adopt(
            self,
            name: str,
            stack: contextlib.ExitStack,
    ) -> None:
        if name in self._held:  # pragma: no cover (name collision)
            stack.close()
        else:
            self._stack.push(stack.pop_all())
            self._held.add(name)

    def close(self) -> None:
        self._stack.close()


def _make_local_repo(directory: str) -> None:
    for resource in _LOCAL_RESOURCES:
        resource_dirname, resource_basename = os.path.split(resource)
        contents = resource_text(f'empty_template_{resource_basename}')
        target_dir = os.path.join(directory, resource_dirname)
        target_file = os.path.join(target_dir, resource_basename)
        os.makedirs(target_dir, exist_ok=True)
        with open(target_file, 'w') as f:
            f.write(contents)


class Store:
    get_default_directory = staticmethod(_get_default_directory)

    def __init__(self, directory: str | None = None) -> None:
        self.directory = directory or Store.get_default_directory()
        self.db_path = os.path.join(self.directory, 'db.db')
        # a unique token for this process's activity markers
        self._token = f'{os.getpid()}-{uuid.uuid4().hex}'
        self._activity: _Activity | None = None
        self.readonly = (
            os.path.exists(self.directory) and
            not os.access(self.directory, os.W_OK)
        )

        if not os.path.exists(self.directory):
            os.makedirs(self.directory, exist_ok=True)
            with open(os.path.join(self.directory, 'README'), 'w') as f:
                f.write(
                    'This directory is maintained by the pre-commit project.\n'
                    'Learn more: https://github.com/pre-commit/pre-commit\n',
                )

        if os.path.exists(self.db_path):
            return
        with self.exclusive_lock():
            # Another process may have already completed this work
            if os.path.exists(self.db_path):  # pragma: no cover (race)
                return
            # To avoid a race where someone ^Cs between db creation and
            # execution of the CREATE TABLE statement
            fd, tmpfile = tempfile.mkstemp(dir=self.directory)
            # We'll be managing this file ourselves
            os.close(fd)
            with self.connect(db_path=tmpfile) as db:
                db.executescript(
                    'CREATE TABLE repos ('
                    '    repo TEXT NOT NULL,'
                    '    ref TEXT NOT NULL,'
                    '    path TEXT NOT NULL,'
                    '    PRIMARY KEY (repo, ref)'
                    ');',
                )
                self._create_configs_table(db)

            # Atomic file move
            os.replace(tmpfile, self.db_path)

    @contextlib.contextmanager
    def exclusive_lock(self) -> Generator[None]:
        def blocked_cb() -> None:  # pragma: no cover (tests are in-process)
            logger.info('Locking pre-commit directory')

        with file_lock.lock(os.path.join(self.directory, '.lock'), blocked_cb):
            yield

    @contextlib.contextmanager
    def connect(
            self,
            db_path: str | None = None,
    ) -> Generator[sqlite3.Connection]:
        db_path = db_path or self.db_path
        # sqlite doesn't close its fd with its contextmanager >.<
        # contextlib.closing fixes this.
        # See: https://stackoverflow.com/a/28032829/812183
        with contextlib.closing(sqlite3.connect(db_path)) as db:
            # this creates a transaction
            with db:
                yield db

    @classmethod
    def db_repo_name(cls, repo: str, deps: Sequence[str]) -> str:
        if deps:
            return f'{repo}:{",".join(deps)}'
        else:
            return repo

    def _marker_filename(self, name: str) -> str:
        return os.path.join(
            self.directory, _ACTIVE_DIRNAME, name, self._token,
        )

    def _hold_marker(
            self,
            stack: contextlib.ExitStack,
            name: str,
    ) -> None:
        """Register an activity marker for the life of ``stack``."""
        filename = self._marker_filename(name)
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, 'w') as f:
            f.write(f'pid: {os.getpid()}\n')
        # remove the marker after the lock is released (the callback runs
        # before the lock context exits because the stack unwinds in
        # reverse)
        stack.callback(_remove_marker, filename)

        def blocked_cb() -> None:  # pragma: no cover (unique token)
            logger.info('Waiting on pre-commit activity marker.')

        stack.enter_context(file_lock.lock(filename, blocked_cb))

    def _resource_name(self, path: str) -> str | None:
        """Return the resource name for a store-managed path, else None."""
        path = os.path.realpath(path)
        parent, name = os.path.split(path)
        if parent == self.directory and name.startswith('repo'):
            return name
        else:
            return None

    @contextlib.contextmanager
    def active(self) -> Generator[None]:
        """Keep the resources used in this context alive across processes.

        Every clone resolved (or created) while active is marked in use
        until the context exits, so a concurrent ``clean``/``gc`` skips it
        instead of deleting it mid-operation.  Markers are released on
        normal exit, failure and interrupts; a process that dies leaves a
        stale marker which later maintenance runs detect and reclaim.
        """
        # re-entrant: a nested command (e.g. `try-repo` calling `run`)
        # shares the surrounding activity
        if self._activity is not None or self.readonly:
            yield
            return

        activity = _Activity(self)
        self._activity = activity
        try:
            activity.hold_name(_SESSION_NAME)
            yield
        finally:
            self._activity = None
            activity.close()

    def _new_repo(
            self,
            repo: str,
            ref: str,
            deps: Sequence[str],
            make_strategy: Callable[[str], None],
    ) -> str:
        original_repo = repo
        repo = self.db_repo_name(repo, deps)

        def _get_result() -> str | None:
            # Check if we already exist
            with self.connect() as db:
                result = db.execute(
                    'SELECT path FROM repos WHERE repo = ? AND ref = ?',
                    (repo, ref),
                ).fetchone()
                return result[0] if result else None

        result = _get_result()
        if result is not None and self._activity is None:
            # no active command -- no marker is needed
            return result
        with self.exclusive_lock():
            # Resolving under the global lock and immediately registering the
            # activity marker makes this atomic with respect to `clean` and
            # `gc`: a maintenance command either sees the marker and leaves
            # the path alone, or it runs first and the (now missing) row is
            # re-created by a fresh clone.
            result = _get_result()
            if result is not None:
                if self._activity is not None:
                    self._activity.hold_path(result)
                return result

            logger.info(f'Initializing environment for {repo}.')

            # the marker is created *before* the directory so a concurrent
            # `clean` can never observe an unprotected half clone
            directory, hold = self._create_repo_directory()
            try:
                with clean_path_on_failure(directory):
                    make_strategy(directory)

                # Update our db with the created repo
                with self.connect() as db:
                    db.execute(
                        'INSERT INTO repos (repo, ref, path) VALUES (?, ?, ?)',
                        [repo, ref, directory],
                    )

                clientlib.warn_for_stages_on_repo_init(
                    original_repo, directory,
                )
            except BaseException:
                # installation failure / ^C leaves no permanent activity
                hold.close()
                raise
            else:
                if self._activity is not None:
                    # keep the clone protected until the command finishes
                    self._activity.adopt(
                        os.path.basename(directory), hold,
                    )
                else:
                    hold.close()

        return directory

    def _create_repo_directory(
            self,
    ) -> tuple[str, contextlib.ExitStack]:
        """Create a fresh repo directory with its activity marker held."""
        while True:
            name = f'repo{uuid.uuid4().hex[:8]}'
            directory = os.path.join(self.directory, name)
            hold = contextlib.ExitStack()
            try:
                self._hold_marker(hold, name)
                os.mkdir(directory, 0o700)
            except FileExistsError:  # pragma: no cover (random collision)
                hold.close()
                continue
            except BaseException:
                hold.close()
                raise
            else:
                return directory, hold

    def _scan_active(self) -> set[str]:
        """Prune stale markers and return names with a live holder.

        A marker whose non-blocking lock can be acquired is stale -- the
        owning process exited (normally, on failure, or after being
        killed) and the operating system released its lock.
        """
        ret: set[str] = set()
        active_dir = os.path.join(self.directory, _ACTIVE_DIRNAME)
        if not os.path.isdir(active_dir):
            return ret

        for name in os.listdir(active_dir):
            group = os.path.join(active_dir, name)
            if not os.path.isdir(group):
                with contextlib.suppress(OSError):
                    os.remove(group)
                continue

            live = False
            try:
                tokens = os.listdir(group)
            except FileNotFoundError:  # pragma: no cover (concurrent prune)
                continue
            for token in tokens:
                marker = os.path.join(group, token)
                # close the lock before unlinking so the file is removable
                # on windows as well
                with file_lock.try_lock(marker) as acquired:
                    stale = acquired
                if stale:
                    with contextlib.suppress(OSError):
                        os.unlink(marker)
                else:
                    live = True

            if live:
                ret.add(name)
            else:
                with contextlib.suppress(OSError):
                    os.rmdir(group)

        with contextlib.suppress(OSError):
            os.rmdir(active_dir)

        return ret

    def _delete_resource(self, path: str) -> None:
        if os.path.islink(path) or not os.path.isdir(path):
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)
        else:
            with contextlib.suppress(FileNotFoundError):
                rmtree(path)

        # a cache entry must never linger in the db once its directory is
        # gone or a later clone would resolve to a missing path
        if os.path.exists(self.db_path):
            with contextlib.suppress(sqlite3.Error, OSError):
                with self.connect() as db:
                    db.execute('DELETE FROM repos WHERE path = ?', (path,))

    def clean(self) -> tuple[list[str], list[str]]:
        """Remove cache resources which are not in active use.

        Returns a ``(removed, deferred)`` tuple of paths.  With no active
        user the whole store (including coordination state) is removed for
        a full clean; otherwise free cache resources are removed and busy
        ones are left behind for the next maintenance run.
        """
        directory = self.directory
        if not os.path.exists(directory):
            return [], []

        active = self._scan_active()
        store_in_use = _SESSION_NAME in active
        busy = active - {_SESSION_NAME}

        removed: list[str] = []
        deferred: list[str] = []
        lock_path = os.path.join(directory, '.lock')

        # don't fight a first clone, environment install or another gc which
        # holds the global lock -- never block on it, just preserve the
        # coordination state in this pass
        with file_lock.try_lock(lock_path) as got_global_lock:
            full_wipe = not store_in_use and not busy and got_global_lock

            for name in os.listdir(directory):
                path = os.path.join(directory, name)
                if name == '.lock':
                    # removed after this lock is released (windows can't
                    # remove an open, locked file)
                    continue
                elif full_wipe:
                    if not os.path.lexists(path):
                        # the marker scan may have pruned an empty `active`
                        continue
                    elif os.path.islink(path) or not os.path.isdir(path):
                        os.remove(path)
                    else:
                        rmtree(path)
                    removed.append(path)
                elif name in _COORDINATION:
                    continue
                elif name in busy:
                    deferred.append(path)
                elif (
                        name.startswith('repo') and
                        os.path.lexists(path) and
                        got_global_lock
                ):
                    self._delete_resource(path)
                    removed.append(path)
                elif name.startswith('repo') and os.path.lexists(path):
                    # a clone, install or gc currently holds the global
                    # lock -- do not race with it, leave cache resources for
                    # a later clean
                    deferred.append(path)
                # scratch files (stash patches, logs, ...) are only safe to
                # remove once no command is active at all

        if not full_wipe:
            return removed, deferred

        # the global lock is released now -- drop it and the empty directory
        try:
            os.remove(lock_path)
            os.rmdir(directory)
        except OSError:  # pragma: no cover (a process started using it)
            # another process recreated state in the tiny race window --
            # report what we actually removed and let a later clean finish
            return removed, []
        else:
            return [directory], []

    def _complete_clone(self, ref: str, git_cmd: Callable[..., None]) -> None:
        """Perform a complete clone of a repository and its submodules """

        git_cmd('fetch', 'origin', '--tags')
        git_cmd('checkout', ref)
        git_cmd('submodule', 'update', '--init', '--recursive')

    def _shallow_clone(self, ref: str, git_cmd: Callable[..., None]) -> None:
        """Perform a shallow clone of a repository and its submodules """

        git_config = 'protocol.version=2'
        git_cmd('-c', git_config, 'fetch', 'origin', ref, '--depth=1')
        git_cmd('checkout', 'FETCH_HEAD')
        git_cmd(
            '-c', git_config, 'submodule', 'update', '--init', '--recursive',
            '--depth=1',
        )

    def clone(self, repo: str, ref: str, deps: Sequence[str] = ()) -> str:
        """Clone the given url and checkout the specific ref."""

        def clone_strategy(directory: str) -> None:
            git.init_repo(directory, repo)
            env = git.no_git_env()

            def _git_cmd(*args: str) -> None:
                cmd_output_b('git', *args, cwd=directory, env=env)

            try:
                self._shallow_clone(ref, _git_cmd)
            except CalledProcessError:
                self._complete_clone(ref, _git_cmd)

        return self._new_repo(repo, ref, deps, clone_strategy)

    def make_local(self, deps: Sequence[str]) -> str:
        return self._new_repo(
            'local', C.LOCAL_REPO_VERSION, deps, _make_local_repo,
        )

    def _create_configs_table(self, db: sqlite3.Connection) -> None:
        db.executescript(
            'CREATE TABLE IF NOT EXISTS configs ('
            '   path TEXT NOT NULL,'
            '   PRIMARY KEY (path)'
            ');',
        )

    def mark_config_used(self, path: str) -> None:
        if self.readonly:  # pragma: win32 no cover
            return
        path = os.path.realpath(path)
        # don't insert config files that do not exist
        if not os.path.exists(path):
            return
        with self.connect() as db:
            # TODO: eventually remove this and only create in _create
            self._create_configs_table(db)
            db.execute('INSERT OR IGNORE INTO configs VALUES (?)', (path,))
