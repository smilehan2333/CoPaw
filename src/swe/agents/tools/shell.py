# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""The shell command tool with tenant path boundary enforcement."""

import asyncio
import ast
import locale
import os
import shlex
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ..tool_failure import ToolExecutionError
from ...app.runner.tool_output_frames import (
    ToolOutputSource,
    emit_tool_output_text,
)
from ...envs.runtime import build_runtime_env
from ...security.tenant_path_boundary import (
    is_path_within_tenant_with_base,
    get_current_tenant_root,
    get_current_tool_base_dir,
    TenantPathBoundaryError,
)
from ...security.python_runtime_path_guard import (
    prepare_python_runtime_path_guard_env,
)

# Commands that take string arguments which may look like paths
# but should NOT be treated as file paths
_STRING_ARG_COMMANDS = frozenset(
    {
        "echo",
        "/bin/echo",
        "/usr/bin/echo",
        "printf",
        "/usr/bin/printf",
    },
)

# Interpreter commands that have dangerous -c/-e code execution flags
# Only for these commands do we reject -c/-e flags
_INTERPRETER_COMMANDS = frozenset(
    {
        # Python code execution temporarily allowed
        # "python", "python3", "python2",
        # "/usr/bin/python", "/usr/bin/python3", "/usr/bin/python2",
        # "/usr/local/bin/python", "/usr/local/bin/python3",
        "node",
        "/usr/bin/node",
        "/usr/local/bin/node",
        "nodejs",
        "/usr/bin/nodejs",
        "ruby",
        "/usr/bin/ruby",
        "/usr/local/bin/ruby",
        "perl",
        "/usr/bin/perl",
        "/usr/local/bin/perl",
        "bash",
        "/bin/bash",
        "/usr/bin/bash",
        "sh",
        "/bin/sh",
        "/usr/bin/sh",
        "zsh",
        "/bin/zsh",
        "/usr/bin/zsh",
        "ksh",
        "/bin/ksh",
        "/usr/bin/ksh",
        "dash",
        "/bin/dash",
        "/usr/bin/dash",
    },
)

_PYTHON_COMMAND_BASENAMES = frozenset(
    {
        "python",
        "python2",
        "python3",
        "pypy",
        "pypy3",
    },
)

_PYTHON_OPTIONS_WITH_VALUE = frozenset({"-W", "-X"})

_PYTHON_PATH_CALL_ARG_INDICES = {
    "open": (0,),
    "io.open": (0,),
    "os.open": (0,),
    "os.stat": (0,),
    "os.listdir": (0,),
    "os.remove": (0,),
    "os.unlink": (0,),
    "os.rmdir": (0,),
    "os.mkdir": (0,),
    "os.makedirs": (0,),
    "os.scandir": (0,),
    "os.rename": (0, 1),
    "os.replace": (0, 1),
    "shutil.copy": (0, 1),
    "shutil.copy2": (0, 1),
    "shutil.copyfile": (0, 1),
    "shutil.copytree": (0, 1),
    "shutil.move": (0, 1),
    "Path": (0,),
    "pathlib.Path": (0,),
    "PurePath": (0,),
    "pathlib.PurePath": (0,),
}

_PYTHON_SCAN_MAX_FILES = 128
_PYTHON_SCAN_MAX_BYTES = 512 * 1024


def _is_path_like(token: str) -> bool:
    """Check if a token looks like a file path.

    Args:
        token: The token to check.

    Returns:
        True if the token looks like a path (starts with /, ./, ../, or ~).
    """
    return token.startswith(("/", "./", "../", "~"))


def _has_code_exec_flag(token: str) -> bool:
    """Check if a token contains code execution flags (-c or -e).

    Handles both standalone flags (-c, -e) and combined flags (-lc, -ec, -ce).
    Only checks the flag part, not whether the command is an interpreter.

    Args:
        token: The token to check (e.g., "-c", "-lc", "--eval").

    Returns:
        True if the token contains -c or -e as code execution flags.
    """
    # Long-form flags that are always code execution
    if token in ("--eval", "--exec", "--command"):
        return True

    # Short-form flags: -c, -e, or combined like -lc, -ec, -ce
    if token.startswith("-") and len(token) > 1:
        # Check if 'c' or 'e' appears in the combined flag
        # But exclude special cases like --option (already handled above)
        flag_body = token[1:]  # Remove leading -
        if "c" in flag_body or "e" in flag_body:
            return True

    return False


def _extract_path_tokens(command: str) -> tuple[list[str], bool]:
    """Extract path tokens from shell command.

    Implements a "path-first" validation strategy:
    - Any token that looks like a path (/..., ./..., ../..., ~...) is validated
    - Only exempt: echo/printf commands (their non-flag args are treated as strings)
    - Interpreter commands with -c/-e flags are flagged for rejection

    Args:
        command: The shell command string.

    Returns:
        Tuple of (file_paths, has_code_exec) where:
        - file_paths: List of explicit file path tokens found
        - has_code_exec: True if interpreter command contains code execution flags
    """
    file_paths = []
    has_code_exec = False

    # Split command into tokens for better parsing
    try:
        tokens = shlex.split(command)
    except ValueError:
        # If shlex fails, fall back to simple parsing
        tokens = command.split()

    if not tokens:
        return file_paths, has_code_exec

    # Check command type
    cmd_name = tokens[0]
    is_exempt_cmd = cmd_name in _STRING_ARG_COMMANDS
    is_interpreter = cmd_name in _INTERPRETER_COMMANDS

    i = 0
    while i < len(tokens):
        token = tokens[i]

        # Check for code execution flags - but ONLY for interpreter commands
        if is_interpreter and _has_code_exec_flag(token):
            has_code_exec = True
            i += 1
            continue

        # Check for path-like tokens
        if _is_path_like(token):
            # For exempt commands (echo/printf), only treat as path if not
            # preceded by a flag (to handle: echo -n "/etc/hosts")
            if is_exempt_cmd:
                if i > 0:
                    prev = tokens[i - 1]
                    if prev.startswith("-"):
                        # This is likely a flag argument, skip
                        pass
                    else:
                        file_paths.append(token)
                else:
                    # First token after command name - for echo/printf this is text
                    pass
            else:
                # Non-exempt command: any path-like token is a file path
                file_paths.append(token)

        i += 1

    return file_paths, has_code_exec


def _is_python_command(command_name: str) -> bool:
    """Return True when the command token names a Python interpreter."""
    basename = Path(command_name).name
    return (
        basename in _PYTHON_COMMAND_BASENAMES
        or basename.startswith("python3.")
        or basename.startswith("python2.")
    )


def _call_name(node: ast.AST) -> Optional[str]:
    """Return dotted call name for simple name/attribute calls."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"
        return node.attr
    return None


def _collect_string_constants(tree: ast.AST) -> dict[str, str]:
    """Collect simple string assignments for static path checks."""
    constants: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(
            node.value.value,
            str,
        ):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = node.value.value
    return constants


def _static_string_value(
    node: ast.AST,
    constants: dict[str, str],
) -> Optional[str]:
    """Resolve literal strings and simple string constants."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _scan_python_source_for_outside_path(
    source: str,
    base_dir: Path,
) -> Optional[str]:
    """Find static Python file-access paths that escape tenant boundary."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    constants = _collect_string_constants(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        call_name = _call_name(node.func)
        if call_name not in _PYTHON_PATH_CALL_ARG_INDICES:
            continue

        for arg_index in _PYTHON_PATH_CALL_ARG_INDICES[call_name]:
            if arg_index >= len(node.args):
                continue
            path_value = _static_string_value(node.args[arg_index], constants)
            if path_value is None:
                continue
            if not is_path_within_tenant_with_base(
                path_value,
                base_dir=base_dir,
            ):
                return path_value

    return None


def _resolve_command_path(token: str, base_dir: Path) -> Path:
    """Resolve a command path token the same way the shell runtime cwd would."""
    path_obj = Path(os.path.expanduser(token))
    if not path_obj.is_absolute():
        path_obj = base_dir / path_obj
    return path_obj.resolve()


def _iter_python_source_files(script_path: Path) -> list[Path]:
    """Return Python source files to scan for a script or package directory."""
    if script_path.is_file():
        return [script_path]
    if not script_path.is_dir():
        return []

    files: list[Path] = []
    for path in script_path.rglob("*.py"):
        files.append(path)
        if len(files) >= _PYTHON_SCAN_MAX_FILES:
            break
    return files


def _find_python_code_source(
    tokens: list[str],
    base_dir: Path,
) -> tuple[str, Optional[str | Path]]:
    """Extract Python source mode from command tokens.

    Returns ("code", source) for ``python -c``, ("path", path) for script or
    directory execution, ("path_outside", token) for a script path that resolves
    outside the tenant, and ("none", None) when there is nothing static to scan.
    """
    i = 1
    while i < len(tokens):
        token = tokens[i]

        if token == "-c":
            if i + 1 < len(tokens):
                return "code", tokens[i + 1]
            return "none", None
        if token.startswith("-c") and len(token) > 2:
            return "code", token[2:]
        if token == "-m" or token.startswith("-m"):
            return "none", None
        if token == "--":
            i += 1
            break
        if token in _PYTHON_OPTIONS_WITH_VALUE:
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        break

    if i >= len(tokens):
        return "none", None

    script_token = tokens[i]
    if script_token == "-":
        return "none", None
    if not is_path_within_tenant_with_base(script_token, base_dir=base_dir):
        return "path_outside", script_token
    return "path", _resolve_command_path(script_token, base_dir)


def _validate_python_script_contents(
    command: str,
    base_dir: Path,
) -> Optional[str]:
    """Validate static Python script/code paths before running Python."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    if not tokens or not _is_python_command(tokens[0]):
        return None

    source_type, source = _find_python_code_source(tokens, base_dir)
    if source_type == "code" and isinstance(source, str):
        outside_path = _scan_python_source_for_outside_path(source, base_dir)
        if outside_path:
            return (
                "Error: Python code contains path outside the allowed workspace: "
                f"'{outside_path}'"
            )
        return None

    if source_type == "path_outside":
        return (
            "Error: Python script path outside the allowed workspace: "
            f"'{source}'"
        )

    if source_type != "path" or not isinstance(source, Path):
        return None

    for script_path in _iter_python_source_files(source):
        if not is_path_within_tenant_with_base(script_path, base_dir=base_dir):
            return (
                "Error: Python script path outside the allowed workspace: "
                f"'{script_path}'"
            )

        try:
            if script_path.stat().st_size > _PYTHON_SCAN_MAX_BYTES:
                continue
            script_source = script_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue

        outside_path = _scan_python_source_for_outside_path(
            script_source,
            base_dir,
        )
        if outside_path:
            return (
                "Error: Python script contains path outside the allowed workspace: "
                f"'{outside_path}'"
            )

    return None


def _validate_shell_paths(command: str, base_dir: Path) -> Optional[str]:
    """Validate that all explicit file paths in the command are within tenant boundary.

    Args:
        command: The shell command to validate.
        base_dir: The base directory for resolving relative paths (typically the cwd).

    Returns:
        Error message if any path escapes the tenant boundary, None otherwise.
    """
    file_paths, has_code_exec = _extract_path_tokens(command)

    # Reject commands with code execution flags (-c, -e, etc.)
    if has_code_exec:
        return (
            "Error: Shell commands with code execution flags (-c, -e, etc.) "
            "are not allowed for security reasons."
        )

    for token in file_paths:
        # Skip checking if it's clearly not a path
        if not token or token in (".", ".."):
            continue

        # Check if the path is within tenant boundary, using base_dir for relative paths
        if not is_path_within_tenant_with_base(token, base_dir=base_dir):
            return (
                f"Error: Shell command contains path outside the allowed workspace: "
                f"'{token}'"
            )

    python_error = _validate_python_script_contents(command, base_dir)
    if python_error:
        return python_error

    return None


def _resolve_cwd(cwd: Optional[Path | str]) -> Path:
    """Resolve and validate the working directory against tenant boundary.

    Args:
        cwd: The requested working directory, or None to default to the current
             agent workspace when available, otherwise the tenant workspace root.

    Returns:
        The resolved working directory path.

    Raises:
        TenantPathBoundaryError: If the cwd is outside the tenant workspace
                                 or tenant context is missing.
    """
    tenant_root = get_current_tenant_root()

    if cwd is None:
        return get_current_tool_base_dir()

    # Resolve the cwd and validate it's within tenant root
    resolved_cwd = Path(cwd).expanduser().resolve()
    try:
        resolved_cwd.relative_to(tenant_root.resolve())
    except ValueError as exc:
        raise TenantPathBoundaryError(
            f"Working directory '{cwd}' is outside the tenant workspace boundary.",
            resolved_path=resolved_cwd,
        ) from exc

    return resolved_cwd


def _kill_process_tree_win32(pid: int) -> None:
    """Kill a process and all its descendants on Windows via taskkill.

    Uses ``taskkill /F /T`` which forcefully terminates the entire process
    tree, including grandchild processes that ``Popen.kill()`` would miss.
    """
    try:
        subprocess.call(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception:
        pass


def _collapse_embedded_newlines(cmd: str) -> str:
    r"""Replace embedded newline characters with spaces in a command string.

    LLMs produce tool-call arguments in JSON where ``\n`` is parsed as an
    actual newline character.  In the original shell command the user
    intended the *literal* two-character sequence ``\n`` (e.g. inside a
    ``--content`` flag), but after JSON decoding it becomes a real line
    break.  When passed to a shell:

    * **Windows** ``cmd.exe`` truncates the command at the first newline.
    * **Unix** ``sh -c`` treats an unquoted newline as a command separator,
      so only the first "line" is executed with its arguments.

    Collapsing these newlines to spaces is a safe default because:

    1. For the bug case (JSON artefact) it prevents truncation.
    2. For intentional multi-line scripts on Windows the ``cmd /D /S /C``
       wrapper *already* breaks at newlines, so this is no worse.
    3. On Unix, callers should prefer ``&&`` / ``;`` over raw newlines for
       multi-command sequences; a stray newline inside an argument is
      almost certainly a JSON artefact.
    """
    if "\n" not in cmd:
        return cmd
    return cmd.replace("\r\n", " ").replace("\n", " ")


def _sanitize_win_cmd(cmd: str) -> str:
    """Fix common LLM escaping artefacts for Windows ``cmd.exe``.

    LLMs sometimes produce commands with backslash-escaped double quotes
    (``\\"``) — valid in bash/JSON but meaningless to ``cmd.exe``.  When
    *every* double-quote in the command is preceded by a backslash, it is
    almost certainly a double-escape artefact, so we strip them.
    """
    if '\\"' in cmd and '"' not in cmd.replace('\\"', ""):
        return cmd.replace('\\"', '"')
    return cmd


def _read_temp_file(path: str) -> str:
    """Read a temporary output file and return its decoded content."""
    try:
        with open(path, "rb") as f:
            return smart_decode(f.read())
    except OSError:
        return ""


# pylint: disable=too-many-branches, too-many-statements
def _execute_subprocess_sync(
    cmd: str,
    cwd: str,
    timeout: int,
    env: dict | None = None,
) -> tuple[int, str, str]:
    """Execute subprocess synchronously in a thread.

    This function runs in a separate thread to avoid Windows asyncio
    subprocess limitations.

    stdout/stderr are redirected to temporary files instead of pipes.
    On Windows, child processes inherit pipe handles and keep them open
    even after the parent exits, which causes ``communicate()`` to block
    until *all* holders close (e.g. a Chrome process launched via
    ``Start-Process``).  With temp-file redirection, ``proc.wait()``
    only waits for the direct child (``cmd.exe``) to exit, so commands
    that spawn background processes return immediately.

    .. note::

       Callers must pre-process *cmd* through
       :func:`_collapse_embedded_newlines` before passing it here.
       ``execute_shell_command`` already does this.

    Args:
        cmd (`str`):
            The shell command to execute (must not contain embedded
            newlines — see note above).
        cwd (`str`):
            The working directory for the command execution.
        timeout (`int`):
            The maximum time (in seconds) allowed for the command to run.
        env (`dict | None`):
            Environment variables for the subprocess.

    Returns:
        `tuple[int, str, str]`:
            A tuple containing the return code, standard output, and
            standard error of the executed command. If timeout occurs, the
            return code will be -1 and stderr will contain timeout information.
    """
    stdout_path: str | None = None
    stderr_path: str | None = None
    stdout_file = None
    stderr_file = None

    try:
        cmd = _sanitize_win_cmd(cmd)
        wrapped = f'cmd /D /S /C "{cmd}"'

        stdout_fd, stdout_path = tempfile.mkstemp(prefix="swe_out_")
        stderr_fd, stderr_path = tempfile.mkstemp(prefix="swe_err_")
        stdout_file = os.fdopen(stdout_fd, "wb")
        stderr_file = os.fdopen(stderr_fd, "wb")

        proc = subprocess.Popen(  # pylint: disable=consider-using-with
            wrapped,
            shell=False,
            stdout=stdout_file,
            stderr=stderr_file,
            text=False,
            cwd=cwd,
            env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )

        # Parent copies are no longer needed — the child inherited its own
        # handles via CreateProcess.  Closing here avoids holding the files
        # open longer than necessary.
        stdout_file.close()
        stdout_file = None
        stderr_file.close()
        stderr_file = None

        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree_win32(proc.pid)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass

        stdout_str = _read_temp_file(stdout_path)
        stderr_str = _read_temp_file(stderr_path)

        if timed_out:
            timeout_msg = (
                f"Command execution exceeded the timeout of {timeout} seconds."
            )
            if stderr_str:
                stderr_str = f"{stderr_str}\n{timeout_msg}"
            else:
                stderr_str = timeout_msg
            return -1, stdout_str, stderr_str

        returncode = proc.returncode if proc.returncode is not None else -1
        return returncode, stdout_str, stderr_str

    except Exception as e:
        return -1, "", str(e)
    finally:
        for f in (stdout_file, stderr_file):
            if f is not None:
                try:
                    f.close()
                except OSError:
                    pass
        for path in (stdout_path, stderr_path):
            if path is not None:
                try:
                    os.unlink(path)
                except OSError:
                    pass


def _tool_text_response(text: str) -> ToolResponse:
    """Build a plain-text tool response."""
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=text,
            ),
        ],
    )


def _raise_shell_error(error_type: str, detail: str) -> None:
    raise ToolExecutionError(error_type=error_type, detail=detail)


def _classify_shell_failure(
    returncode: int,
    stderr_str: str,
) -> str:
    if returncode == -1 or "TimeoutError:" in stderr_str:
        return "tool_timeout"
    if "outside the allowed workspace" in stderr_str:
        return "permission_denied"
    return "shell_command_failed"


def _prepare_subprocess_env() -> dict[str, str]:
    """Prepare subprocess environment with tenant env and active Python PATH."""
    env = build_runtime_env()
    python_bin_dir = str(Path(sys.executable).parent)
    existing_path = env.get("PATH", "")
    env["PATH"] = (
        python_bin_dir + os.pathsep + existing_path
        if existing_path
        else python_bin_dir
    )
    return env


def _format_shell_response(
    returncode: int,
    stdout_str: str,
    stderr_str: str,
) -> str:
    """Format shell execution output for a tool response."""
    if returncode == 0:
        response_text = (
            stdout_str or "Command executed successfully (no output)."
        )
        if stderr_str:
            response_text += f"\n[stderr]\n{stderr_str}"
        return response_text

    response_parts = [f"Command failed with exit code {returncode}."]
    if stdout_str:
        response_parts.append(f"\n[stdout]\n{stdout_str}")
    if stderr_str:
        response_parts.append(f"\n[stderr]\n{stderr_str}")
    return "".join(response_parts)


async def _terminate_unix_process_group(
    proc: asyncio.subprocess.Process,
) -> None:
    """Terminate a Unix subprocess group, escalating to SIGKILL if needed."""
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        pgid = proc.pid
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    if not await _wait_for_unix_process_group_exit(pgid, proc, timeout=2):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            return
        await _wait_for_unix_process_group_exit(pgid, proc, timeout=2)


def _unix_process_group_exists(pgid: int) -> bool:
    """Return whether any process is still present in the process group."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    return True


async def _wait_for_unix_process_group_exit(
    pgid: int,
    proc: asyncio.subprocess.Process,
    timeout: float,
) -> bool:
    """Wait for the spawned process group to disappear."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while _unix_process_group_exists(pgid):
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        delay = min(0.05, remaining)
        if proc.returncode is None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.sleep(delay)
    return True


async def _drain_unix_subprocess_output(
    proc: asyncio.subprocess.Process,
) -> tuple[bytes, bytes]:
    """Drain any remaining subprocess output after termination."""
    try:
        return await asyncio.wait_for(proc.communicate(), timeout=1)
    except asyncio.TimeoutError:
        return b"", b""


async def _handle_unix_subprocess_timeout(
    proc: asyncio.subprocess.Process,
    timeout: int,
) -> tuple[int, str, str]:
    """Handle Unix subprocess timeout and collect best-effort output."""
    stderr_suffix = (
        f"⚠️ TimeoutError: The command execution exceeded "
        f"the timeout of {timeout} seconds. "
        f"Please consider increasing the timeout value if this command "
        f"requires more time to complete."
    )
    try:
        await _terminate_unix_process_group(proc)
        stdout, stderr = await _drain_unix_subprocess_output(proc)
        stdout_str = smart_decode(stdout)
        stderr_str = smart_decode(stderr)
        if stderr_str:
            stderr_str += f"\n{stderr_suffix}"
        else:
            stderr_str = stderr_suffix
        return -1, stdout_str, stderr_str
    except (ProcessLookupError, OSError):
        try:
            proc.kill()
            await proc.wait()
        except (ProcessLookupError, OSError):
            pass
        return -1, "", stderr_suffix


async def _execute_unix_subprocess(
    cmd: str,
    working_dir: Path,
    timeout: int,
    env: dict[str, str],
) -> tuple[int, str, str]:
    """Execute a shell command on Unix-like platforms."""
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []

    def _decode_live_chunk(chunk: bytes) -> str:
        try:
            return chunk.decode("utf-8")
        except UnicodeDecodeError:
            encoding = locale.getpreferredencoding(False) or "utf-8"
            return chunk.decode(encoding, errors="replace")

    async def _read_stream(
        stream: asyncio.StreamReader | None,
        source: ToolOutputSource,
        chunks: list[bytes],
    ) -> None:
        if stream is None:
            return
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            chunks.append(chunk)
            await emit_tool_output_text(source, _decode_live_chunk(chunk))

    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        bufsize=0,
        cwd=str(working_dir),
        env=env,
        start_new_session=True,
    )

    if not all(hasattr(proc, attr) for attr in ("stdout", "stderr", "wait")):
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
        returncode = proc.returncode if proc.returncode is not None else -1
        return returncode, smart_decode(stdout), smart_decode(stderr)

    stdout_task = asyncio.create_task(
        _read_stream(proc.stdout, "stdout", stdout_chunks),
    )
    stderr_task = asyncio.create_task(
        _read_stream(proc.stderr, "stderr", stderr_chunks),
    )
    wait_task: asyncio.Task[int] | None = None

    try:
        wait_task = asyncio.create_task(proc.wait())
        tasks = (wait_task, stdout_task, stderr_task)
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        if pending:
            raise asyncio.TimeoutError
        returncode = proc.returncode if proc.returncode is not None else -1
        for task in done:
            task.result()
        return (
            returncode,
            smart_decode(b"".join(stdout_chunks)),
            smart_decode(b"".join(stderr_chunks)),
        )
    except asyncio.TimeoutError:
        stderr_suffix = (
            f"⚠️ TimeoutError: The command execution exceeded "
            f"the timeout of {timeout} seconds. "
            f"Please consider increasing the timeout value if this command "
            f"requires more time to complete."
        )
        try:
            await _terminate_unix_process_group(proc)
        except (ProcessLookupError, OSError):
            try:
                proc.kill()
                await proc.wait()
            except (ProcessLookupError, OSError):
                pass
        timeout_tasks: list[Awaitable[Any]] = [stdout_task, stderr_task]
        if wait_task is not None:
            timeout_tasks.append(wait_task)
        try:
            await asyncio.wait_for(
                asyncio.gather(*timeout_tasks, return_exceptions=True),
                timeout=1,
            )
        except asyncio.TimeoutError:
            pass
        stdout_str = smart_decode(b"".join(stdout_chunks))
        stderr_str = smart_decode(b"".join(stderr_chunks))
        if stderr_str:
            stderr_str += f"\n{stderr_suffix}"
        else:
            stderr_str = stderr_suffix
        await emit_tool_output_text("stderr", stderr_suffix)
        return -1, stdout_str, stderr_str
    finally:
        for task in (stdout_task, stderr_task, wait_task):
            if task is not None and not task.done():
                task.cancel()


async def _execute_platform_subprocess(
    cmd: str,
    working_dir: Path,
    timeout: int,
    env: dict[str, str],
) -> tuple[int, str, str]:
    """Execute a shell command on the active platform."""
    if sys.platform == "win32":
        # Windows: use thread pool to avoid asyncio subprocess limitations
        return await asyncio.to_thread(
            _execute_subprocess_sync,
            cmd,
            str(working_dir),
            timeout,
            env,
        )
    return await _execute_unix_subprocess(cmd, working_dir, timeout, env)


# pylint: disable=too-many-branches, too-many-statements
async def execute_shell_command(
    command: str,
    timeout: int = 60,
    cwd: Optional[Path | str] = None,
) -> ToolResponse:
    """Execute a shell command and return its output.

    Platform shells: Windows uses cmd.exe; Linux/macOS use /bin/sh or /bin/bash.

    IMPORTANT: Always consider the operating system before choosing commands.

    Args:
        command (`str`):
            The shell command to execute.
        timeout (`int`, defaults to `60`):
            The maximum time (in seconds) allowed for the command to run.
            Default is 60 seconds.
        cwd (`Optional[Path]`, defaults to `None`):
            The working directory for the command execution.
            If None, defaults to the current agent workspace when available and
            otherwise falls back to the tenant workspace root.

    Returns:
        `ToolResponse`:
            The tool response containing the return code, standard output, and
            standard error of the executed command. If timeout occurs, the
            return code will be -1 and stderr will contain timeout information.
    """

    cmd = _collapse_embedded_newlines((command or "").strip())

    # Intercept command and inject tenant isolation params if applicable
    from .shell_interceptor import intercept_command

    cmd, _was_intercepted = intercept_command(cmd)

    # Validate and resolve the working directory against tenant boundary
    try:
        working_dir = _resolve_cwd(cwd)
    except TenantPathBoundaryError as e:
        _raise_shell_error("permission_denied", f"Error: {e}")

    # Validate explicit path tokens in the command, using working_dir as base for relative paths
    path_error = _validate_shell_paths(cmd, base_dir=working_dir)
    if path_error:
        error_type = (
            "permission_denied"
            if "outside the allowed workspace" in path_error
            else "invalid_arguments"
        )
        _raise_shell_error(error_type, path_error)

    env = _prepare_subprocess_env()
    python_runtime_guard = prepare_python_runtime_path_guard_env(
        env,
        tenant_root=get_current_tenant_root(),
        base_dir=working_dir,
    )

    try:
        with python_runtime_guard:
            (
                returncode,
                stdout_str,
                stderr_str,
            ) = await _execute_platform_subprocess(
                cmd,
                working_dir,
                timeout,
                env,
            )

        response_text = _format_shell_response(
            returncode,
            stdout_str,
            stderr_str,
        )
        if returncode != 0:
            _raise_shell_error(
                _classify_shell_failure(returncode, stderr_str),
                response_text,
            )

        return _tool_text_response(response_text)

    except Exception as e:
        if isinstance(e, ToolExecutionError):
            raise
        _raise_shell_error(
            "unexpected_tool_error",
            f"Error: Shell command execution failed due to \n{e}",
        )


def smart_decode(data: bytes) -> str:
    try:
        decoded_str = data.decode("utf-8")
    except UnicodeDecodeError:
        encoding = locale.getpreferredencoding(False) or "utf-8"
        decoded_str = data.decode(encoding, errors="replace")

    return decoded_str.strip("\n")
