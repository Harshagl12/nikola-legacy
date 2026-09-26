import sqlite3
import re
from datetime import datetime
from pathlib import Path

from backend.autofill import AutofillEngine

from typing import Optional

class ProfileLearner:
    def __init__(self, autofill: Optional[AutofillEngine] = None, db_path: Optional[str] = None):
        self.autofill = autofill
        if db_path:
            self.db_path = Path(db_path)
        else:
            nikola_dir = Path.home() / ".nikola"
            nikola_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = nikola_dir / "nikola_learning.db"
            old_db = Path.home() / "nikola_learning.db"
            if old_db.exists() and not self.db_path.exists():
                try:
                    old_db.replace(self.db_path)
                except Exception:
                    pass
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS corrections(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    field_label TEXT,
                    field_type TEXT,
                    field_placeholder TEXT,
                    profile_key TEXT,
                    was_llm_suggestion BOOL,
                    accepted BOOL
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS learned_patterns(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern TEXT UNIQUE,
                    profile_key TEXT,
                    confidence FLOAT,
                    times_confirmed INT DEFAULT 1
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS profile_learned(
                    profile_key TEXT,
                    value TEXT,
                    confidence REAL,
                    last_updated TEXT,
                    source TEXT
                )
            ''')
            
            # Verify profile_learned schema using PRAGMA table_info
            expected_schema = {
                'profile_key': 'TEXT',
                'value': 'TEXT',
                'confidence': 'REAL',
                'last_updated': 'TEXT',
                'source': 'TEXT'
            }
            cols = conn.execute("PRAGMA table_info(profile_learned)").fetchall()
            current_schema = {col[1]: col[2].upper() for col in cols}
            
            needs_rebuild = False
            for col_name, expected_type in expected_schema.items():
                if col_name not in current_schema or current_schema[col_name] != expected_type:
                    needs_rebuild = True
                    break
            
            if needs_rebuild:
                conn.execute("DROP TABLE IF EXISTS profile_learned")
                conn.execute('''
                    CREATE TABLE profile_learned(
                        profile_key TEXT,
                        value TEXT,
                        confidence REAL,
                        last_updated TEXT,
                        source TEXT
                    )
                ''')

    def log_correction(self, field_label, field_type, field_placeholder, profile_key, was_llm_suggestion, accepted):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                'INSERT INTO corrections (timestamp, field_label, field_type, field_placeholder, profile_key, was_llm_suggestion, accepted) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (datetime.utcnow().isoformat(), field_label, field_type, field_placeholder, profile_key, was_llm_suggestion, accepted)
            )
            if accepted:
                self._update_learned_pattern(field_label, field_placeholder, profile_key, conn)

    def _update_learned_pattern(self, label, placeholder, profile_key, conn):
        pattern = self._normalize(f"{label}|{placeholder}")
        
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT profile_key, confidence, times_confirmed FROM learned_patterns WHERE pattern=?', (pattern,)).fetchone()
        
        if row:
            if row['profile_key'] == profile_key:
                new_conf = min(1.0, row['confidence'] + 0.1) if row['times_confirmed'] + 1 >= 3 else row['confidence']
                conn.execute(
                    'UPDATE learned_patterns SET times_confirmed = times_confirmed + 1, confidence = ? WHERE pattern = ?',
                    (new_conf, pattern)
                )
            else:
                conn.execute(
                    'UPDATE learned_patterns SET profile_key = ?, times_confirmed = 1, confidence = 0.7 WHERE pattern = ?',
                    (profile_key, pattern)
                )
        else:
            conn.execute(
                'INSERT INTO learned_patterns (pattern, profile_key, confidence, times_confirmed) VALUES (?, ?, 0.7, 1)',
                (pattern, profile_key)
            )

    def _normalize(self, text: str) -> str:
        s = re.sub(r'[^a-z0-9]', '', str(text).lower().strip())
        return s[:120]

    async def suggest_from_learned(self, form_fields: list[dict]) -> dict:
        mappings = {}
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            for field in form_fields:
                label = field.get('label', '')
                placeholder = field.get('placeholder', '')
                name = field.get('name', '')
                pattern = self._normalize(f"{label}|{placeholder}")
                
                row = conn.execute('SELECT profile_key, confidence FROM learned_patterns WHERE pattern=?', (pattern,)).fetchone()
                
                if row and row['confidence'] >= 0.7:
                    mappings[name] = {
                        'profile_key': row['profile_key'],
                        'confidence': row['confidence'],
                        'source': 'learned'
                    }
                else:
                    llm_result = await self.autofill.map_fields([field])
                    mappings[name] = {
                        'profile_key': llm_result.get('mappings', {}).get(name),
                        'confidence': llm_result.get('confidence', {}).get(name, 0.5),
                        'source': 'llm'
                    }
        
        final_mappings = {k: v['profile_key'] for k, v in mappings.items() if v['profile_key']}
        final_confidence = {k: v['confidence'] for k, v in mappings.items()}
        sources = {k: v['source'] for k, v in mappings.items()}
        
        return {
            'mappings': final_mappings,
            'confidence': final_confidence,
            'sources': sources,
            'total_fields': len(form_fields)
        }

    def get_learning_stats(self) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            total_corr = conn.execute('SELECT COUNT(*) FROM corrections').fetchone()[0]
            total_pat = conn.execute('SELECT COUNT(*) FROM learned_patterns').fetchone()[0]
            high_conf = conn.execute('SELECT COUNT(*) FROM learned_patterns WHERE confidence >= 0.9').fetchone()[0]
            accepted = conn.execute('SELECT COUNT(*) FROM corrections WHERE accepted=1').fetchone()[0]
            
            return {
                'total_corrections': total_corr,
                'total_patterns': total_pat,
                'high_confidence_patterns': high_conf,
                'acceptance_rate': (accepted / total_corr) if total_corr > 0 else 0.0
            }
