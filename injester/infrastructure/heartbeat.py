"""
Live Heartbeat & Vigorous Progress Logger for Long-Running Operations.
Provides periodic, non-blocking terminal updates while awaiting remote LLM APIs,
free-tier model queues (OpenRouter, HuggingFace, etc.), or heavy GPU/CPU workloads.
"""

import os
import sys
import time
import threading
from typing import Optional


class HeartbeatLogger:
    """
    Context manager that starts a background daemon thread to emit periodic
    heartbeat messages to stdout/stderr while a synchronous, blocking network
    or compute call is executing.
    """

    def __init__(
        self,
        stage: str,
        model_name: str = "",
        detail: str = "",
        interval: float = 6.0,
        provider: str = "",
    ):
        self.stage = stage
        self.model_name = model_name
        self.detail = detail
        self.interval = interval
        self.provider = provider
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.t0 = time.time()

    def _log(self, msg: str):
        # In MCP mode, stdout is reserved for JSON-RPC frames; route all logs to stderr
        if os.getenv("INJESTER_MCP_ACTIVE") == "1":
            sys.stderr.write(msg + "\n")
            sys.stderr.flush()
        else:
            print(msg, flush=True)

    def __enter__(self):
        self.t0 = time.time()
        now = time.strftime("%H:%M:%S")
        target = f" to '{self.model_name}'" if self.model_name else ""
        detail_msg = f" ({self.detail})" if self.detail else ""
        self._log(f"  [{self.stage} {now}] 🚀 Sending prompt{target}{detail_msg}...")
        self._log(f"  [{self.stage} {now}] ⏳ Awaiting response (remote / free-tier models may queue; active timeout: 600s)...")
        
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self

    def _run(self):
        while not self.stop_event.wait(self.interval):
            elapsed = int(time.time() - self.t0)
            now = time.strftime("%H:%M:%S")
            note = ""
            
            # Contextual hints based on elapsed time and model
            if elapsed >= 30 and (elapsed % 30 < self.interval):
                low_model = self.model_name.lower()
                if "free" in low_model or "openrouter" in self.provider.lower():
                    note = " ⚠️ [OpenRouter free tier: model may be queued behind priority requests]"
                elif "gemini" in low_model:
                    note = " ⚡ [Gemini endpoint: generating structured response]"
                elif "ollama" in self.provider.lower() or "localhost" in self.provider.lower():
                    note = " 🖥️ [Local Ollama: running on local hardware]"
                else:
                    note = " ⏳ [Awaiting completion stream]"

            self._log(f"  [{self.stage} {now}] ⏳ Still processing... [{elapsed}s elapsed]{note}")

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        elapsed = time.time() - self.t0
        now = time.strftime("%H:%M:%S")
        if exc_type is None:
            self._log(f"  [{self.stage} {now}] ✨ Response received successfully in {elapsed:.2f}s")
        else:
            self._log(f"  [{self.stage} {now}] ❌ Request failed after {elapsed:.2f}s: {exc_val}")
        return False
