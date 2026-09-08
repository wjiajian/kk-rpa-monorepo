"""Install immutable releases in independent directories, without business execution."""
import asyncio
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import ssl
import tarfile
import tempfile
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler
from uuid import UUID

from .deployments import deployment_metadata

MAX_ARCHIVE = 512 * 1024 * 1024
PROCESS_TIMEOUT = 900


class CleanupUncertain(Exception):
    """The install process tree has not confirmed termination."""


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def extract_source(archive, destination):
    total, names = 0, set()
    with tarfile.open(archive, "r:") as source:
        for entry in source:
            relative = PurePosixPath(entry.name)
            if (relative.is_absolute() or ".." in relative.parts or "\\" in entry.name or ":" in entry.name
                    or not (entry.isdir() or entry.isfile()) or entry.name in names):
                raise ValueError("源码制品包含不支持的路径或文件")
            names.add(entry.name)
            total += entry.size
            if total > MAX_ARCHIVE:
                raise ValueError("源码制品超过 512 MiB")
            path = destination.joinpath(*relative.parts)
            if not path.resolve().is_relative_to(destination.resolve()):
                raise ValueError("源码制品路径越界")
            if entry.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("wb") as output:
                    shutil.copyfileobj(source.extractfile(entry), output)
                path.chmod(0o755 if entry.mode & 0o111 else 0o644)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("制品下载不接受重定向")


class Installer:
    def __init__(self, root, server_url, token, ca_file=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.root / "installed.json"
        self.registry = json.loads(self.registry_path.read_text(encoding="utf-8")) if self.registry_path.exists() else {}
        self.server_url, self.token, self.ca_file = server_url, token, ca_file
        self.worker_config = self.root / "worker.json"

    def download(self, path, destination):
        server = urlsplit(self.server_url)
        if not path.startswith("/api/robot-deployment-jobs/") or urlsplit(path).netloc:
            raise ValueError("制品下载地址无效")
        url = urlunsplit(("https", server.netloc, path, "", ""))
        opener = build_opener(HTTPSHandler(context=ssl.create_default_context(cafile=self.ca_file)), NoRedirect())
        request = Request(url, headers={"Authorization": "Bearer " + self.token, "ngrok-skip-browser-warning": "1"})
        with opener.open(request, timeout=60) as response, destination.open("wb") as output:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_ARCHIVE:
                    raise ValueError("源码制品超过 512 MiB")
                output.write(chunk)

    def resolve_interrupted(self, command):
        """Called offline after the operator confirms the install processes stopped."""
        release_id, job_id = command["release_id"], command["job_id"]
        for value in (release_id, job_id):
            if str(UUID(value)) != value:
                raise ValueError("部署作业或发布版本 ID 无效")
        if command["action"] not in {"install", "uninstall"}:
            raise ValueError("不支持的部署操作")
        if command["action"] == "install" and release_id in self.registry:
            raise ValueError("已注册版本不能作为未完成安装清理，请重连核对安装结果")
        directory = self.root / release_id
        quarantine = self.root / "interrupted" / job_id
        if directory.exists():
            quarantine.parent.mkdir(exist_ok=True)
            if quarantine.exists():
                raise ValueError("已存在该作业的隔离目录，请先核对现场")
            directory.rename(quarantine)
        if command["action"] == "uninstall":
            updated = {key: value for key, value in self.registry.items() if key != release_id}
            atomic_json(self.registry_path, updated)
            self.registry = updated
            return "uninstalled"
        return "failed"

    async def run_process(self, args, cwd):
        # Application install/tests receive no robot, model or business credentials.
        env = {key: value for key, value in os.environ.items() if key in {
            "PATH", "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR",
            "SSL_CERT_FILE", "SSL_CERT_DIR"}}
        process = await asyncio.create_subprocess_exec(*args, cwd=cwd, env=env,
            **({"start_new_session": True} if os.name != "nt" else {}),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            code = await asyncio.wait_for(process.wait(), PROCESS_TIMEOUT)
        except (asyncio.TimeoutError, asyncio.CancelledError) as error:
            try:
                if os.name == "nt":
                    killer = await asyncio.create_subprocess_exec("taskkill", "/PID", str(process.pid), "/T", "/F",
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                    if await asyncio.wait_for(killer.wait(), 30):
                        raise CleanupUncertain()
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                await asyncio.wait_for(process.wait(), 30)
            except (OSError, asyncio.TimeoutError, CleanupUncertain):
                raise CleanupUncertain() from None
            if isinstance(error, asyncio.CancelledError):
                raise
            raise ValueError("安装或离线检查超时") from None
        if code:
            raise ValueError(f"命令退出码 {code}")

    async def execute(self, command, report):
        release_id = command.get("release_id")
        directory = None
        stage = "prepare"
        try:
            try:
                if str(UUID(release_id)) != release_id:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise ValueError("发布版本 ID 无效") from None
            directory = self.root / release_id
            if command["action"] == "uninstall":
                stage = "uninstall"
                await report("installing", "uninstall")
                # Remove registry only after deleting the directory succeeds.
                await asyncio.to_thread(shutil.rmtree, directory)
                updated = {key: value for key, value in self.registry.items() if key != release_id}
                atomic_json(self.registry_path, updated)
                self.registry = updated
                await report("uninstalled", "complete")
                return
            if command["action"] != "install":
                raise ValueError("不支持的部署操作")
            if release_id in self.registry:
                await report("installed", "complete")
                return
            if directory.exists():
                # A previous known failed install may leave partial files; no installed version is replaced.
                await asyncio.to_thread(shutil.rmtree, directory)
            directory.mkdir()
            repository = directory / "repository"
            repository.mkdir()
            stage = "download"
            await report("installing", stage)
            with tempfile.TemporaryDirectory(prefix="rpa-download-", dir=self.root) as temporary:
                archive = Path(temporary) / "source.tar"
                await asyncio.to_thread(self.download, command["artifact_url"], archive)
                stage = "extract"
                await report("installing", stage)
                await asyncio.to_thread(extract_source, archive, repository)
            spec = command["deployment"]
            app_path = (repository / spec["path"]).resolve()
            if not app_path.is_relative_to(repository.resolve()) or not (app_path / "app.toml").is_file():
                raise ValueError("发布应用路径无效")
            deployment = {key: spec[key] for key in ("app_id", "version", "module", "package", "allowed_hosts")}
            python = app_path / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            deployment.update(cwd=str(app_path), python=str(python), release_id=release_id, commit=command["commit"])
            metadata = deployment_metadata(deployment)
            if metadata.get("schema_status") != "valid" or metadata.get("input_schema") != spec["input_schema"]:
                raise ValueError("制品参数声明与发布版本不一致")
            stage = "dependencies"
            await report("installing", stage)
            await self.run_process(["uv", "sync", "--locked", "--python", "3.12"], app_path)
            for stage in ("doctor", "test"):
                await report("installing", stage)
                await self.run_process(["uv", "run", "--no-sync", "rpa-app", stage,
                    *(["--deployment"] if stage == "doctor" else [])], app_path)
            updated = {**self.registry, release_id: deployment}
            atomic_json(self.registry_path, updated)
            self.registry = updated
            await report("installed", "complete")
        except (CleanupUncertain, asyncio.CancelledError):
            # Cancellation may interrupt a filesystem/download thread; do not race it with cleanup.
            await report("uncertain", stage, "安装中断，进程和目录收尾待确认")
        except Exception as error:
            cleanup_error = None
            if command.get("action") == "install" and directory is not None and release_id not in self.registry:
                try:
                    if directory.exists():
                        await asyncio.to_thread(shutil.rmtree, directory)
                except OSError as cleanup:
                    cleanup_error = cleanup
            # Report the stage and error type, never arbitrary program output.
            detail = f"{stage}：{error}" if type(error) is ValueError else f"{stage}：{type(error).__name__}"
            uncertain = cleanup_error or command.get("action") == "uninstall" or release_id in self.registry
            await report("uncertain" if uncertain else "failed", stage, detail)
