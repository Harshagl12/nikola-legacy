import sqlite3
import pytest
from backend.profile_learner import ProfileLearner
from backend.workflow_memory import WorkflowMemory

def test_profile_learner_migration(tmp_path):
    db_path = tmp_path / "test_profile.db"
    
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE profile_learned (profile_key INT, value INT)")
        conn.execute("INSERT INTO profile_learned VALUES (123, 456)")
        
    learner = ProfileLearner(db_path=str(db_path))
    
    with sqlite3.connect(db_path) as conn:
        cols = conn.execute("PRAGMA table_info(profile_learned)").fetchall()
        col_names = [col[1] for col in cols]
        assert "source" in col_names
        assert "confidence" in col_names
        assert "profile_key" in col_names

def test_workflow_memory_migration(tmp_path):
    db_path = tmp_path / "test_workflow.db"
    
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE workflow_memory (id INTEGER PRIMARY KEY, timestamp TEXT, action TEXT, details TEXT)")
        
    mem = WorkflowMemory(db_path=str(db_path))
    
    with sqlite3.connect(db_path) as conn:
        cols = conn.execute("PRAGMA table_info(workflow_memory)").fetchall()
        col_names = [col[1] for col in cols]
        assert "input_text" in col_names
        assert "success" in col_names
