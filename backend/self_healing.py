import os
import asyncio
from datetime import datetime
from pathlib import Path
import shutil
import subprocess

from backend.llm_engine import get_llm

from backend.config import settings
from backend.nl_processor import NLProcessor
from backend.rag import RAGPipeline
from backend.logger import get_logger

logger = get_logger(__name__)

STRATEGY_REGISTRY = {
    'file_op': [
        'direct_path',
        'fuzzy_vault_search',
        'expand_home',
        'downloads_fallback',
    ],
    'app_launch': [
        'startfile',
        'where_command',
        'program_files',
        'start_menu_search',
    ],
    'rag_query': [
        'rag_retrieval',
        'direct_llm',
        'broader_query',
    ],
}

class SelfHealingAgent:
    def __init__(self, nl: NLProcessor, rag: RAGPipeline):
        self.nl = nl
        self.rag = rag
        self.max_retries = 3

    async def execute_with_healing(self, text: str, intent: str, initial_result: dict) -> dict:
        healing_log = []
        strategies = STRATEGY_REGISTRY.get(intent, [])

        for strategy in strategies[:self.max_retries]:
            healing_log.append({
                'strategy': strategy,
                'attempted_at': datetime.utcnow().isoformat()
            })

            try:
                result = await self._try_strategy(strategy, text, intent)
                if result.get('success'):
                    healing_log[-1]['outcome'] = 'SUCCESS'
                    explanation = await self._explain_healing(text, strategy, healing_log)
                    result['healing_log'] = healing_log
                    result['healing_explanation'] = explanation
                    result['was_healed'] = True
                    if 'action' not in result:
                        result['action'] = initial_result.get('action', 'unknown')
                    if 'description' not in result:
                        result['description'] = initial_result.get('description', '')
                    return result
                else:
                    healing_log[-1]['outcome'] = f"FAILED: {result.get('error','')}"
            except Exception as e:
                healing_log[-1]['outcome'] = f"EXCEPTION: {str(e)[:100]}"

        # Check for hardware crashes in the log
        hardware_crash = any("0xc000001d" in e.get('outcome', '') or "ILLEGAL" in e.get('outcome', '') for e in healing_log)
        if hardware_crash:
            return {
                'success': False,
                'was_healed': False,
                'healing_log': healing_log,
                'error': 'Hardware compatibility issue',
                'healing_explanation': 'CPU does not support AVX2 instructions',
                'action': 'hardware_error',
                'description': "My AI engine crashed because your CPU doesn't support the required AVX2 instructions. Commands like 'hi' need the AI to respond."
            }

        return {
            'success': False,
            'was_healed': False,
            'healing_log': healing_log,
            'error': 'All recovery strategies exhausted.',
            'healing_explanation': self._format_failure_summary(healing_log),
            'action': initial_result.get('action', 'unknown'),
            'description': initial_result.get('description', '')
        }

    async def _try_strategy(self, strategy: str, text: str, intent: str) -> dict:
        loop = asyncio.get_event_loop()
        
        if strategy == 'fuzzy_vault_search':
            vault = Path(settings.VAULT_PATH).expanduser()
            if vault.exists():
                matches = [f for f in vault.rglob('*')
                           if any(w in f.name.lower()
                                  for w in text.lower().split() if len(w) > 3) and f.is_file()]
                if matches:
                    return await loop.run_in_executor(None, self.nl._read_file, str(matches[0]))
            return {'success': False, 'error': 'No fuzzy match found'}

        elif strategy == 'rag_retrieval':
            chunks, sources = await self.rag.query(text, top_k=3)
            if chunks:
                return {'success': True, 'result': {'response': chunks[0]}, 'description': chunks[0][:50], 'action': 'rag_retrieval_fallback', 'sources': sources}
            return {'success': False, 'error': 'RAG search returned no results'}

        elif strategy == 'expand_home':
            expanded = os.path.expandvars(os.path.expanduser(text))
            return await loop.run_in_executor(None, self.nl.process_command, expanded)

        elif strategy == 'direct_llm':
            llm = get_llm()
            response = await loop.run_in_executor(
                None, lambda: llm.create_chat_completion(messages=[{'role':'user','content': text}])
            )
            return {'success': True, 'result': {'response': response['choices'][0]['message']['content']}, 'description': response['choices'][0]['message']['content'][:50], 'action': 'direct_llm_fallback'}

        elif strategy == 'broader_query':
            prompt = f'Rephrase this query using simpler, broader terms: "{text}". Reply ONLY the rephrased query.'
            llm = get_llm()
            response = await loop.run_in_executor(
                None, lambda: llm.create_chat_completion(messages=[{'role':'user','content': prompt}])
            )
            broader = response['choices'][0]['message']['content'].strip()
            chunks, sources = await self.rag.query(broader, top_k=3)
            if chunks:
                return {'success': True, 'result': {'response': chunks[0]}, 'description': chunks[0][:50], 'action': 'broader_rag_fallback', 'sources': sources}
            return {'success': False, 'error': 'Broader query returned no results'}

        elif strategy == 'where_command':
            words = text.lower().split()
            for word in words:
                found = shutil.which(word)
                if found:
                    proc = subprocess.Popen([found], creationflags=0x08000000)
                    return {'success': True, 'result': {'pid': proc.pid}, 'description': f'Launched {found}', 'action': 'which_launch'}
            return {'success': False, 'error': 'Executable not found in PATH'}

        return {'success': False, 'error': f'Strategy {strategy} not applicable'}

    async def _explain_healing(self, text, winning_strategy, log) -> str:
        tried = [e['strategy'] for e in log if e['outcome'] != 'SUCCESS']
        prompt = (f'I was asked: "{text}". '
                  f'I first tried: {tried} and they failed. '
                  f'Then I succeeded using: {winning_strategy}. '
                  f'Write ONE short sentence explaining what I did. '
                  f'Write from first person as NIKOLA.')
        loop = asyncio.get_event_loop()
        try:
            llm = get_llm()
            response = await loop.run_in_executor(
                None, lambda: llm.create_chat_completion(messages=[{'role':'user','content': prompt}])
            )
            return response['choices'][0]['message']['content'].strip()
        except:
            return f"I recovered from a failure using {winning_strategy}."

    def _format_failure_summary(self, log) -> str:
        tried = [e['strategy'] for e in log]
        return f"I tried {len(tried)} approaches ({', '.join(tried)}) but couldn't complete the task."
