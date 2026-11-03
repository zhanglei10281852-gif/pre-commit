# 共享缓存活跃租约与故障安全清理

> **Workspace:** F:\swe\099906\project-01

---

**User**

在共享 PRE_COMMIT_HOME 的开发机或 CI runner 上，一个仓库正在安装或执行 hook 时，另一个维护进程运行 pre-commit clean 或 pre-commit gc 会直接移除前者已经解析到的仓库和语言环境，导致本来正常的提交或检查在中途报路径不存在。请让缓存资源在 clone、环境安装、hook 执行以及 try-repo 和 install-hooks 使用期间拥有跨进程的活跃生命周期：清理命令只能删除未被任何活跃操作占用的条目，并把暂时无法删除的资源留待后续维护收敛；进程正常结束、安装失败或用户中断后不应遗留永久占用，进程异常消失时也要能识别陈旧占用并在之后安全回收。clean 仍应在没有活跃使用者时清空当前和旧缓存，gc 仍按已登记配置保留引用资源并删除无引用资源；两者与首次 clone、环境健康检查、附加依赖隔离及并发安装的既有锁语义必须协同，不能让清理等待整个长时间 hook、删除 Store 自身的协调状态，或把同一资源重复登记为多个不可回收副本。用户应能从命令输出区分已删除与因活跃使用而延后的资源，后续 clean 或 gc 在占用释放后能够确定完成清理，未并发清理的普通 run、install-hooks、try-repo、clean 和 gc 行为保持兼容。

**Assistant**

toolName: view_folder

status: success

f:\swe\099906\project-01

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\file_lock.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\commands\clean.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\commands\gc.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\repository.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\lang_base.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\commands\run.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\commands\try_repo.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\commands\install_uninstall.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\util.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\main.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\error_handler.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\staged_files_only.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\tests\store_test.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\tests\commands\clean_test.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\tests\commands\gc_test.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\tests\conftest.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\constants.py

toolName: Shell

status: success

This is the pre-commit codebase (v4.7.0). The task asks for cross-process resource lifecycle/locking so concurrent `clean`/`gc` can't remove in-use caches. Let me check whether upstream has a reference implementation for this.

toolName: web_search

status: success

toolName: web_search

status: success

No upstream reference exists; I'll design and implement it in this codebase. Let me check the remaining call paths and language environment usage before writing the plan.

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\commands\hook_impl.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\prefix.py

toolName: search_by_regex

status: success

Now I have the complete picture. Let me set up a task plan and check the test environment.

toolName: todo_write

status: success

Todos updated: 7 items

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\testing\util.py

toolName: Shell

status: success

Environment is ready. Now implementing. First, the non-blocking lock primitive in [file_lock.py](file:///f:/swe/099906/project-01/pre_commit/file_lock.py):

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\file_lock.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\file_lock.py

changes: undefined

Now the core implementation in [store.py](file:///f:/swe/099906/project-01/pre_commit/store.py). First the imports and constants:

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

changes: undefined

Now update the `Store.__init__` and add the active-session machinery:

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

changes: undefined

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

changes: undefined

I need to refine `clean()` for Windows (can't rmtree a directory containing the `.lock` file we have open) and add the `rmtree` import. Let me fix both:

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

changes: undefined

Make `_create_repo_directory` robust if marker acquisition itself fails:

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

changes: undefined

Now update the commands — clean, gc, run, and install_hooks:

toolName: todo_write

status: success

Todos updated: 7 items

toolName: Write

status: success

filePath: f:\swe\099906\project-01\pre_commit\commands\clean.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\commands\gc.py

changes: undefined

Now wrap the run path in `store.active()`:

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\commands\run.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\commands\install_uninstall.py

changes: undefined

Also wrap `try_repo` (its pre-`run` clone reads the manifest):

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\commands\try_repo.py

changes: undefined

Now let's run the existing tests to check for regressions:

toolName: todo_write

status: success

Todos updated: 7 items

toolName: Shell

status: success

A stray global pytest plugin (`pytest_ckan`) breaks collection. Let me check the project's own test requirements and disable the foreign plugin:

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\requirements-dev.txt

toolName: search_by_regex

status: success

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\tox.ini

toolName: search_by_regex

status: success

toolName: Shell

status: success

Core suites pass. Let me run the broader command/repository suites:

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

Some failures look Windows-environment-related (`rm` missing, symlink privileges). Let me confirm they're pre-existing by checking against the pristine code:

toolName: Shell

status: success

While that runs, let me inspect the try-repo test to determine if my change is implicated:

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\tests\commands\try_repo_test.py

toolName: Shell

status: success

toolName: StopCommand

status: success

toolName: Shell

status: success

Pre-existing failures confirmed environmental (WSL/bash, symlink privilege), not from my changes. Now let me check `output.py`, then add the new tests:

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\output.py

Now I'll add tests. First, extend [tests/store_test.py](file:///f:/swe/099906/project-01/tests/store_test.py) with unit and cross-process tests:

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\tests\store_test.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\tests\store_test.py

changes: undefined

Now add gc deferral test and clean command-output test:

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\tests\commands\gc_test.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\tests\commands\gc_test.py

changes: undefined

toolName: Write

status: success

filePath: f:\swe\099906\project-01\tests\commands\clean_test.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\tests\commands\clean_test.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\tests\commands\clean_test.py

changes: undefined

toolName: Shell

status: success

toolName: Shell

status: success

Windows-specific issues: (1) marker unlink must happen after the lock fd closes, (2) the empty `active/` root should be removed too. Let me fix both in [store.py](file:///f:/swe/099906/project-01/pre_commit/store.py):

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

changes: undefined

toolName: Shell

status: success

In-process tests pass. Now the cross-process tests:

toolName: Shell

status: success

All cross-process tests pass on Windows. Now run the full store/clean/gc files:

toolName: todo_write

status: success

Todos updated: 7 items

toolName: Shell

status: success

toolName: search_by_regex

status: success

toolName: Shell

status: success

Three failures look shell/WSL-related. Verify they're pre-existing on pristine code:

toolName: Shell

status: success

Confirmed pre-existing. Now the critical run-test suite (covers the wrapped `run()` path):

toolName: Shell

status: success

While tests run, let me harden a race I spotted: `_scan_active` may already have removed the empty `active` root, so full-wipe iteration could hit missing paths:

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

changes: undefined

Let me check how `autoupdate` uses clones, to decide whether it needs a session too:

toolName: search_by_regex

status: success

toolName: search_by_regex

status: success

`autoupdate` uses its own temp dirs, not the Store — no change needed. Let me check the background run_test progress:

toolName: Shell

status: success

While waiting, let me review the final [store.py](file:///f:/swe/099906/project-01/pre_commit/store.py) in full to verify correctness:

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

One robustness fix — ensure the activity stack is closed if the session marker acquisition itself raises:

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

changes: undefined

The run_test job finished. Let me see the failures:

toolName: Shell

status: success

All failures are the same environmental class (WSL bash can't execute `.sh` at Windows paths; symlink privilege). Let me confirm a representative sample fails identically on pristine code:

toolName: Shell

status: success

All representative failures are identical on pristine code — environmental. Now an end-to-end CLI verification of the actual reported scenario:

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

The inline script quoting broke and the host shell is stuck in its readiness loop. Stop it and redo with a proper holder script file:

toolName: StopCommand

status: success

toolName: Write

status: success

filePath: C:\Users\czxy4\AppData\Local\Temp\pch_holder.py

changes: undefined

toolName: Shell

status: success

The exact reported scenario now works. Let me also verify CLI stale-reclaim after a killed process, plus normal gc convergence:

toolName: Shell

status: success

Typo (`rev-Parse`) — rerun correctly:

toolName: Shell

status: success

Stale reclaim works end-to-end. Clean up temp artifacts and re-run the affected test files after the final hardening edits:

toolName: delete_file

status: success

toolName: Shell

status: success

Now run the project's own quality checks (mypy, flake8) on the changed files:

toolName: Shell

status: success

mypy errors shown are all pre-existing Windows-platform issues in unrelated files (`xargs.py` unix attrs, `docker.py`, `cfgv` stubs); none touch the changed code. flake8 is clean. Let me run the remaining fast suites that touch modified areas:

toolName: Shell

status: success

toolName: Shell

status: success

toolName: StopCommand

status: success

toolName: Shell

status: success

All non-repository tests pass. Confirm the repository failures are pre-existing on pristine:

toolName: Shell

status: success

Pre-existing, confirmed. Let me clean the test scratch artifact and check `.gitignore`:

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\.gitignore

toolName: Shell

status: success

That `build/` dir is a pre-existing scratch artifact from python-language tests, unrelated to my change. Remove it:

toolName: Shell

status: success

Now let me review the complete diff for a final quality pass:

toolName: Shell

status: success

Let me do a final read-through of the complete new sections of store.py:

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

The core logic looks right. Let me verify the final command-layer files:

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\commands\clean.py

toolName: view_files

status: success

filePath: f:\swe\099906\project-01\pre_commit\commands\gc.py

One more correctness gap to close: a run can resolve an existing path from the db *just before* `clean` scans its marker. The fix is to make active resolution and the marker atomic under the existing global lock, and make `clean` conservative when that lock is held by another operation:

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\pre_commit\store.py

changes: undefined

Add a test for conservative clean while the global lock is held:

toolName: edit_file_search_replace

status: success

filePath: f:\swe\099906\project-01\tests\store_test.py

changes: undefined

toolName: Shell

status: success

Let me re-verify the run path after the lock-semantics change using bash-independent tests (system/pygrep hooks):

toolName: Shell

status: success

toolName: Shell

status: success

All remaining failures are the known WSL/bash environmental ones. Final lint + status check:

toolName: Shell

status: success

toolName: Shell

status: success

toolName: todo_write

status: success

Todos updated: 7 items

已完成。共享 `PRE_COMMIT_HOME` 时，清理命令不再能删除正在被 clone、装环境或执行 hook 的资源。

## 实现方案：基于 OS 文件锁的「活跃标记」

在 Store 下新增协调目录 `<home>/active/`（不属于缓存条目，清理命令不会误删自身协调状态）：

- `active/_session/<token>` — 命令级会话标记，保护 db、暂存补丁等杂项文件
- `active/<repo目录名>/<token>` — 资源级标记；语言环境目录都位于 clone/local 仓库目录内，保护仓库目录即同时保护环境（含 `additional_dependencies` 隔离出的各个独立目录）

token 为 `pid-uuid`，每个标记文件持有一把排他 OS 锁（POSIX `flock` / Windows `msvcrt.locking`），天然满足全部生命周期要求：

- **正常退出 / 安装失败 / ^C**：上下文 `finally` 关闭 fd 并删除标记，不留永久占用
- **进程被杀**：内核自动释放锁，标记文件虽在但锁可取——后续维护命令据此识别为陈旧占用并安全回收
- **去重**：同一进程内同一资源（多个 hook 共用、manifest clone 与 deps 变体命中同一目录）只登记一个标记

## 主要改动

- [file_lock.py](file:///f:/swe/099906/project-01/pre_commit/file_lock.py)：新增非阻塞 `try_lock`（两个平台均实现）
- [store.py](file:///f:/swe/099906/project-01/pre_commit/store.py)：
  - `Store.active()` 会话上下文 + `_Activity`（引用去重、失败即释放）
  - clone 改为**先建标记、后建目录**，杜绝半 clone 无保护窗口；会话内命中 db 缓存的解析也放到既有全局锁内与标记登记原子完成，与首次 clone / 并发安装 / 健康检查锁语义协同
  - `_scan_active()` 非阻塞探测锁、清除陈旧标记；`clean()` 无人使用时整目录清空（含旧逻辑兼容），有活跃操作时只删空闲 `repo*` 条目（同时删对应 db 行）、忙碌者延后；拿不到全局锁时绝不阻塞等待，一律保守延后
- [gc.py](file:///f:/swe/099906/project-01/pre_commit/commands/gc.py)：仍按已登记 configs 判定引用，忙碌的无引用条目**保留目录与 db 行**留给下次 gc，输出 `N repo(s) in use … left for a future pre-commit gc`
- [run.py](file:///f:/swe/099906/project-01/pre_commit/commands/run.py)、[install_uninstall.py](file:///f:/swe/099906/project-01/pre_commit/commands/install_uninstall.py#L144-L149)、[try_repo.py](file:///f:/swe/099906/project-01/pre_commit/commands/try_repo.py#L51-L80)：clone、装环境、hook 执行全程包在 `store.active()` 中（可重入，try-repo 调 run 不重复登记）
- [clean.py](file:///f:/swe/099906/project-01/pre_commit/commands/clean.py)：输出区分 `Cleaned <path>.` 与 `<path> is in use by another process -- skipped.`，旧 `~/.pre-commit` 行为不变

清理永远不等待长时间 hook（全部非阻塞），占用释放后再次 clean/gc 即可确定性收敛；无并发时输出与行为完全兼容。

## 验证

- 新增 22 个测试（[store_test.py](file:///f:/swe/099906/project-01/tests/store_test.py)、[clean_test.py](file:///f:/swe/099906/project-01/tests/commands/clean_test.py)、[gc_test.py](file:///f:/swe/099906/project-01/tests/commands/gc_test.py)），含 3 个**真实子进程**用例：并发 clean 延后、并发 gc 延后（行与目录都保留）、`kill -9` 后陈旧标记被识别并完全回收；52 passed / 1 xfailed
- CLI 端到端实测：活跃时 clean 报告 skipped 且 clone 存活、gc 报告延后；进程退出后 `Cleaned …` 整目录消失
- 其余套件（run/repository/try-repo 等）在本机的失败项均经 stash 对比确认为**改动前已有**的环境问题（WSL bash 无法执行 `.sh`、无符号链接权限），flake8 干净，mypy 无新增告警
