import subprocess
import time
import os
import pytest
from nikola_launcher.process_manager import kill_port, ProcessManager

def test_port_cleanup():
    port = 8888
    
    cmd = [
        "python", "-c",
        f"import socket, time; s=socket.socket(); s.bind(('127.0.0.1', {port})); s.listen(1); time.sleep(10)"
    ]
    proc = subprocess.Popen(cmd)
    
    try:
        time.sleep(1.0)
        assert proc.poll() is None
        
        kill_port(port)
        
        start = time.time()
        while proc.poll() is None and (time.time() - start) < 3.0:
            time.sleep(0.2)
            
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait()

def test_kill_port_8000_method():
    pm = ProcessManager()
    pm._kill_port_8000()
