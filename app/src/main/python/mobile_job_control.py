"""
mobile_job_control.py - Controlador Thread-Safe de Pausa, Retomada e Cancelamento
Permite pausar ou interromper traduções no Android preservando páginas já salvas.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import threading
import time


class JobCancelledError(BaseException):
    """Exceção dedicada de cancelamento seguro (atravessa except Exception)."""
    pass


class JobController:
    """Gerencia estado de pausa e cancelamento cooperativo da tradução mobile."""

    def __init__(self):
        self._lock = threading.Lock()
        self._run_event = threading.Event()
        self._run_event.set()
        self._cancel_event = threading.Event()

    def reset(self):
        with self._lock:
            self._cancel_event.clear()
            self._run_event.set()

    def pause(self):
        with self._lock:
            if self._cancel_event.is_set():
                return False
            self._run_event.clear()
            return True

    def resume(self):
        with self._lock:
            if self._cancel_event.is_set():
                return False
            self._run_event.set()
            return True

    def stop(self):
        with self._lock:
            self._cancel_event.set()
            self._run_event.set()
            return True

    def is_paused(self):
        return (not self._run_event.is_set()) and (not self._cancel_event.is_set())

    def is_cancelled(self):
        return self._cancel_event.is_set()

    def checkpoint(self):
        """Aguarda enquanto pausado e interrompe com segurança se cancelado."""
        while not self._run_event.is_set():
            if self._cancel_event.is_set():
                raise JobCancelledError("Tradução interrompida pelo usuário.")
            time.sleep(0.25)
        if self._cancel_event.is_set():
            raise JobCancelledError("Tradução interrompida pelo usuário.")
