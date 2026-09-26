from unittest.mock import MagicMock, patch
import time
import pytest
from nikola_launcher.process_manager import ProcessManager

def test_watchdog_crash_cap():
    pm = ProcessManager()
    
    mock_tray = MagicMock()
    pm.tray = mock_tray
    
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 1
    pm.processes['backend'] = mock_proc
    
    pm.start_backend = MagicMock()
    
    original_sleep = time.sleep
    sleep_count = 0
    
    def mock_sleep(seconds):
        if seconds == 30:
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 6:
                pm.watchdog_active = False
        else:
            original_sleep(seconds)
            
    with patch("time.sleep", side_effect=mock_sleep):
        pm.start_watchdog()
        pm.watchdog_thread.join(timeout=2.0)
        
    assert pm.restart_count['backend'] == 5
    assert len(pm.restart_timestamps['backend']) == 5
    assert pm.start_backend.call_count == 5
    
    mock_tray.notify.assert_called_once()
    args, kwargs = mock_tray.notify.call_args
    assert "Service Crash Cap Hit" in args[0]
    assert "failed 5 times" in args[1]
