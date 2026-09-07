import argparse
import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import ssl
import sys
from time import time
import tomllib
from urllib.parse import urlsplit

from websockets.asyncio.client import connect

from .journal import Journal


class Client:
    def __init__(self, config_path):
        self.path = Path(config_path).resolve()
        self.config = tomllib.loads(self.path.read_text(encoding="utf-8"))
        if urlsplit(self.config["server_url"]).scheme != "wss":
            raise ValueError("robot connections require wss and a trusted certificate")
        self.lock_file = open(self.path.with_suffix(".lock"), "a+b")
        if os.name == "nt":
            import msvcrt
            self.lock_file.write(b"0")
            self.lock_file.flush()
            self.lock_file.seek(0)
            msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.journal = Journal(self.path.parent / self.config.get("journal", "executor.sqlite"))
        self.worker = self.reader = self.socket = None
        self.outbound = asyncio.Queue()
        self.state = self.journal.state()
        self.clock_offset = self.state.get("clock_offset", 0)
        # A lost local process has uncertain effects. Never recreate a running action.
        for command in self.journal.interrupted():
            self.journal.append({"type": "result", "console_run_id": command["console_run_id"],
                "execution_attempt_id": command["execution_attempt_id"], "request_id": command["request_id"],
                "status": "unknown", "result": {"error": "执行端进程重启，操作结果待确认"}})
        if self.state.get("active_run"):
            self.state["phase"] = "unknown"
            self.journal.save_state(self.state)

    async def input(self, message):
        if self.worker and self.worker.returncode is None:
            try:
                self.worker.stdin.write((json.dumps(message) + "\n").encode())
                await self.worker.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                # read_worker records the exit; a broken pipe cannot prove whether an action ran.
                return False
            return True
        return False

    def acknowledge(self, run_id, seq):
        if (run_id == self.state.get("active_run") and self.state.get("ended_seq")
                and seq >= self.state["ended_seq"]):
            self.state = {}
            self.journal.save_state(self.state)

    async def command(self, command):
        if command["action"] == "start":
            if self.state.get("active_run") not in {None, command["console_run_id"]}:
                raise ValueError("robot already owns another run")
        elif self.state.get("active_run") != command["console_run_id"]:
            raise ValueError("command does not belong to active run")
        if not self.journal.accept(command):
            # Replay persisted responses/events, not browser operations.
            for event in self.journal.events(command["console_run_id"]):
                await self.outbound.put(event)
            return
        if command["action"] == "start":
            snapshot = command["params"]["snapshot"]
            self.state = {"active_run": command["console_run_id"],
                          "execution_attempt_id": command["execution_attempt_id"], "phase": "starting"}
            self.journal.save_state(self.state)
            deployed = next(((key, d) for key, d in self.config["deployments"].items()
                             if d["app_id"] == snapshot["app_id"] and d["version"] == snapshot["version"]), None)
            if deployed is None:
                await self.preparation_failed(command, "本机未部署指定应用版本")
                return
            key, deployment = deployed
            try:
                self.worker = await asyncio.create_subprocess_exec(
                    deployment["python"], "-u", str(Path(__file__).with_name("worker.py")),
                    "--config", str(self.path), "--deployment", key,
                    cwd=deployment["cwd"], stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    # Never relay arbitrary application stdout to dashboard/model.
                    stderr=asyncio.subprocess.DEVNULL, limit=16 * 1024 * 1024)
            except OSError as error:
                await self.preparation_failed(command, f"应用 Python 环境无法启动：{type(error).__name__}")
                return
            self.reader = asyncio.create_task(self.read_worker(command))
        if not self.worker or self.worker.returncode is not None:
            event = self.journal.append({"type": "result", "console_run_id": command["console_run_id"],
                "execution_attempt_id": command["execution_attempt_id"], "request_id": command["request_id"],
                "status": "unknown", "result": {"error": "执行进程不可用；保留占用"}})
            await self.outbound.put(event)
            return
        await self.input(command)

    async def preparation_failed(self, command, error):
        result = self.journal.append({"type": "result", "console_run_id": command["console_run_id"],
            "execution_attempt_id": command["execution_attempt_id"], "request_id": command["request_id"],
            "status": "failed", "result": {"phase": "prepare", "error": error}})
        ended = self.journal.append({"type": "ended", "console_run_id": command["console_run_id"],
            "execution_attempt_id": command["execution_attempt_id"], "data": {"reason": "执行环境准备失败，未启动浏览器"}})
        self.state.update(phase="ended", ended_seq=ended["seq"])
        self.journal.save_state(self.state)
        await self.outbound.put(result)
        await self.outbound.put(ended)

    async def read_worker(self, start_command):
        process = self.worker
        owner = self.state["active_run"]
        startup_error = None
        async for raw in process.stdout:
            message = json.loads(raw)
            kind = message["type"]
            if kind == "startup_error":
                startup_error = message["data"]["error"]
                continue
            event = self.journal.append({**message, "at": time() + self.clock_offset})
            if kind in {"program_started", "recovery_started", "attempt_finished", "ended", "uncertain"}:
                self.state.update(execution_attempt_id=message["execution_attempt_id"],
                    phase={"program_started": "program", "recovery_started": "recovery",
                           "attempt_finished": "failed", "ended": "ended", "uncertain": "unknown"}[kind])
                if kind == "ended":
                    # Keep the last run reference for replay until server acks the end.
                    self.state["ended_seq"] = event["seq"]
                self.journal.save_state(self.state)
            await self.outbound.put(event)
        await process.wait()
        if startup_error:
            await self.preparation_failed(start_command, startup_error)
            return
        if self.state.get("active_run") == owner and self.state.get("phase") != "ended":
            event = self.journal.append({"type": "uncertain", "console_run_id": self.state["active_run"],
                "execution_attempt_id": self.state["execution_attempt_id"], "data": {"error": "执行进程退出，结束未确认"}})
            await self.outbound.put(event)

    async def run(self):
        tls = ssl.create_default_context(cafile=self.config.get("ca_file"))
        headers = {"Authorization": "Bearer " + os.environ[self.config["credential_env"]]}
        while True:
            try:
                async with connect(self.config["server_url"], ssl=tls, additional_headers=headers,
                                   max_size=16 * 1024 * 1024, ping_interval=15, ping_timeout=15) as socket:
                    self.socket = socket
                    hello = {"type": "hello", **self.state, "journal_complete": True,
                             "requests": self.journal.requests(), "deployments": [
                                 {"app_id": d["app_id"], "version": d["version"]} for d in self.config["deployments"].values()]}
                    await socket.send(json.dumps(hello))
                    sync = json.loads(await socket.recv())
                    if sync["type"] != "sync":
                        raise ValueError("server refused reconciliation")
                    self.clock_offset = sync["server_time"] - time()
                    self.state["clock_offset"] = self.clock_offset
                    self.journal.save_state(self.state)
                    if self.state.get("active_run"):
                        for event in self.journal.events(self.state["active_run"], sync.get("after_seq", 0)):
                            await socket.send(json.dumps(event))
                    self.acknowledge(sync.get("console_run_id"), sync["after_seq"])
                    await socket.send(json.dumps({"type": "ready"}))
                    await self.input({"type": "connection", "connected": True})
                    async def send():
                        while True:
                            await socket.send(json.dumps(await self.outbound.get()))
                    sender = asyncio.create_task(send())
                    try:
                        async for raw in socket:
                            message = json.loads(raw)
                            if message["type"] == "command":
                                await self.command(message)
                            elif message["type"] == "ack":
                                self.acknowledge(message["console_run_id"], message["seq"])
                    finally:
                        sender.cancel()
                        with suppress(asyncio.CancelledError):
                            await sender
            except (OSError, ValueError, StopIteration) as error:
                print(f"连接或现场核对失败：{type(error).__name__}", file=sys.stderr)
            except Exception as error:
                print(f"控制连接中断：{type(error).__name__}", file=sys.stderr)
            finally:
                self.socket = None
                await self.input({"type": "connection", "connected": False})
            await asyncio.sleep(3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    asyncio.run(Client(args.config).run())
