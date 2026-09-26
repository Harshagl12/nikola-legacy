import json
import re
from backend.llm_engine import get_llm

from backend.config import settings

class IntentClassifier:
    INTENT_TAXONOMY = {
        'file_op':    ['open','read','delete','copy','move','list','find'],
        'rag_query':  ['what','explain','summarize','tell me','how does'],
        'system_op':  ['disk','cpu','ram','process','info','status'],
        'app_launch': ['launch','start','open app','run'],
        'voice_op':   ['say','speak','read aloud','tell'],
        'screenshot': ['screenshot','screen','capture','show desktop'],
        'autofill':   ['fill','autofill','remember','profile','form'],
        'workflow':   ['workflow','automate','repeat','always'],
    }

    def classify_intent(self, text: str) -> list[dict]:
        scores = {}
        text_lower = text.lower()
        for intent, keywords in self.INTENT_TAXONOMY.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[intent] = score / len(keywords)
                
        top = sorted(scores.items(), key=lambda x: -x[1])
        if top and top[0][1] >= 0.6:
            return [{
                'intent': top[0][0],
                'confidence': round(top[0][1], 2),
                'description': self._intent_description(top[0][0], text),
                'action': top[0][0]
            }]
            
        prompt = f"""User said: "{text}"
Possible intents: {list(self.INTENT_TAXONOMY.keys())}
Return ONLY a JSON array of up to 3 objects, most likely first:
[{{\"intent\": \"...\", \"confidence\": 0.0-1.0, \"description\": \"...\"}}]
No explanation. Only JSON."""

        try:
            llm = get_llm()
            response = llm.create_chat_completion(messages=[{'role':'user','content': prompt}])
            raw = response['choices'][0]['message']['content'].strip()
            
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            results = json.loads(match.group()) if match else []
            for r in results:
                r['confidence'] = max(0.0, min(1.0, float(r.get('confidence', 0.5))))
                r['action'] = r['intent']
                r['description'] = r.get('description', self._intent_description(r['intent'], text))
            return results[:3] if results else self._fallback_intent(text)
        except Exception:
            return self._fallback_intent(text)
            
    def _fallback_intent(self, text: str):
        return [{'intent':'rag_query','confidence':0.4,
                 'description':'Answer as general question','action':'ask'}]

    def _intent_description(self, intent: str, text: str) -> str:
        descriptions = {
            'file_op':    f'Perform file operation: {text[:60]}',
            'rag_query':  f'Search knowledge base for: {text[:60]}',
            'system_op':  'Get system information',
            'app_launch': f'Launch application mentioned in: {text[:40]}',
            'voice_op':   'Speak text aloud via TTS',
            'screenshot': 'Capture and analyze desktop screenshot',
            'autofill':   'Fill or manage autofill profile',
            'workflow':   'Create or run automated workflow',
        }
        return descriptions.get(intent, f'Process: {text[:60]}')
