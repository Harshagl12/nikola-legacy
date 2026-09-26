import sqlite3
import json
import hashlib
from uuid import uuid4
from datetime import datetime
from pathlib import Path
import networkx as nx

from backend.llm_engine import get_llm

from backend.config import settings
from backend.logger import get_logger
from backend.nl_processor import NLProcessor

logger = get_logger(__name__)

from typing import Optional

class WorkflowMemory:
    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self.db_path = Path(db_path)
        else:
            nikola_dir = Path.home() / ".nikola"
            nikola_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = nikola_dir / "nikola_workflows.db"
            old_db = Path.home() / "nikola_workflows.db"
            if old_db.exists() and not self.db_path.exists():
                try:
                    old_db.replace(self.db_path)
                except Exception:
                    pass
        self._init_db()
        self.graph = nx.DiGraph()
        self.session_id = uuid4().hex
        self.session_actions = []
        self._pending_suggestion = None

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS action_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    action_type TEXT,
                    action_detail TEXT,
                    session_id TEXT
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS workflows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_hash TEXT UNIQUE,
                    actions TEXT,
                    frequency INT,
                    last_seen TEXT,
                    user_confirmed BOOL
                )
            ''')
            # Verify workflow_memory schema using PRAGMA table_info
            cols = conn.execute("PRAGMA table_info(workflow_memory)").fetchall()
            current_cols = {col[1] for col in cols}
            
            if not {'action', 'input_text', 'timestamp', 'success'}.issubset(current_cols):
                conn.execute("DROP TABLE IF EXISTS workflow_memory")
                conn.execute('''
                    CREATE TABLE workflow_memory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        action TEXT,
                        input_text TEXT,
                        timestamp TEXT,
                        success BOOLEAN
                    )
                ''')
            else:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS workflow_memory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        action TEXT,
                        input_text TEXT,
                        timestamp TEXT,
                        success BOOLEAN
                    )
                ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_workflow_memory_action_timestamp
                ON workflow_memory (action, timestamp)
            ''')

    def log_action(self, action_type: str, action_detail: str):
        timestamp = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                'INSERT INTO action_log (timestamp, action_type, action_detail, session_id) VALUES (?, ?, ?, ?)',
                (timestamp, action_type, action_detail, self.session_id)
            )
        self.session_actions.append((action_type, action_detail))
        if len(self.session_actions) >= 3:
            self._detect_pattern()

    def _detect_pattern(self):
        last_3 = self.session_actions[-3:]
        pattern_hash = hashlib.sha256(json.dumps(last_3).encode()).hexdigest()[:16]
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute('SELECT * FROM workflows WHERE pattern_hash = ?', (pattern_hash,)).fetchone()
            
            if row:
                conn.execute(
                    'UPDATE workflows SET frequency = frequency + 1, last_seen = ? WHERE pattern_hash = ?',
                    (datetime.utcnow().isoformat(), pattern_hash)
                )
                if row['frequency'] + 1 >= 2 and not row['user_confirmed']:
                    self._suggest_workflow(last_3, pattern_hash)
            else:
                conn.execute(
                    'INSERT INTO workflows (pattern_hash, actions, frequency, last_seen, user_confirmed) VALUES (?, ?, 1, ?, 0)',
                    (pattern_hash, json.dumps(last_3), datetime.utcnow().isoformat())
                )

    def _suggest_workflow(self, actions: list[tuple], pattern_hash: str):
        prompt = f"""These 3 actions were done in sequence again:
{actions}
Write a SHORT friendly suggestion (1 sentence) asking if the user wants to automate this as a workflow. Reply ONLY the suggestion text."""
        try:
            llm = get_llm()
            response = llm.create_chat_completion(
                messages=[{'role': 'user', 'content': prompt}]
            )
            suggestion = response['choices'][0]['message']['content'].strip()
            self._pending_suggestion = {
                'pattern_hash': pattern_hash,
                'suggestion': suggestion,
                'actions': actions
            }
        except Exception as e:
            logger.error("Failed to generate workflow suggestion", error=str(e))

    def get_pending_suggestion(self) -> dict | None:
        suggestion = self._pending_suggestion
        self._pending_suggestion = None
        return suggestion

    def confirm_workflow(self, pattern_hash: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('UPDATE workflows SET user_confirmed = 1 WHERE pattern_hash = ?', (pattern_hash,))
            row = conn.execute('SELECT actions FROM workflows WHERE pattern_hash = ?', (pattern_hash,)).fetchone()
            if row:
                actions = json.loads(row[0])
                for i in range(len(actions) - 1):
                    self.graph.add_edge(str(actions[i]), str(actions[i+1]))
        logger.info("Workflow confirmed", pattern_hash=pattern_hash)

    def execute_workflow(self, pattern_hash: str, nl_processor: NLProcessor) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute('SELECT actions FROM workflows WHERE pattern_hash = ?', (pattern_hash,)).fetchone()
        
        if not row:
            return [{'success': False, 'error': 'Workflow not found'}]
            
        actions = json.loads(row[0])
        results = []
        for action_type, action_detail in actions:
            res = nl_processor.process_command(action_detail)
            results.append(res)
        return results

    def get_all_workflows(self) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute('SELECT * FROM workflows WHERE user_confirmed = 1').fetchall()
            return [{'id': r['id'], 'pattern_hash': r['pattern_hash'], 'actions': json.loads(r['actions']), 'frequency': r['frequency'], 'last_seen': r['last_seen']} for r in rows]

    def delete_workflow(self, pattern_hash: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('DELETE FROM workflows WHERE pattern_hash = ?', (pattern_hash,))
