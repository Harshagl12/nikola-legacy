"""
Autofill Profile Engine for NIKOLA backend.
Manages encrypted profile storage and form field mapping via LLM.
"""

import asyncio
import json
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from backend.llm_engine import get_llm

from backend.config import settings
from backend.logger import get_logger

logger = get_logger(__name__)


class AutofillEngine:
    """Fernet-encrypted JSON profile manager."""

    def __init__(self):
        """Initialize autofill engine with encryption."""
        self.profile_path = Path(settings.AUTOFILL_PROFILE_PATH).expanduser().resolve()
        
        # Initialize cipher
        if not settings.AUTOFILL_ENCRYPTION_KEY:
            raise ValueError("AUTOFILL_ENCRYPTION_KEY not set in .env")
        
        self.cipher = Fernet(settings.AUTOFILL_ENCRYPTION_KEY.encode())
        logger.info("Autofill engine initialized", profile_path=str(self.profile_path))

    def save_profile(self, data: dict) -> None:
        """Save profile dict encrypted to file. NEVER log values.
        
        Args:
            data: Profile dictionary
        """
        try:
            # Serialize to JSON
            json_data = json.dumps(data).encode()
            
            # Encrypt
            encrypted = self.cipher.encrypt(json_data)
            
            # Write to file
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.profile_path, "wb") as f:
                f.write(encrypted)
            
            logger.info("Profile saved", field_count=len(data))
        except Exception as e:
            logger.error("Failed to save profile", error=str(e))
            raise

    def load_profile(self) -> dict:
        """Load and decrypt profile from file.
        
        Returns:
            Profile dict (empty if file not exists)
        """
        try:
            if not self.profile_path.exists():
                return {}
            
            with open(self.profile_path, "rb") as f:
                encrypted = f.read()
            
            # Decrypt
            json_data = self.cipher.decrypt(encrypted)
            profile = json.loads(json_data.decode())
            
            logger.debug("Profile loaded", field_count=len(profile))
            return profile
        except Exception as e:
            logger.error("Failed to load profile", error=str(e))
            return {}

    def add_field(self, field: str, value: str) -> int:
        """Add or update profile field.
        
        Args:
            field: Field name
            value: Field value (NEVER logged)
            
        Returns:
            Total field count after add
        """
        try:
            profile = self.load_profile()
            profile[field] = value
            self.save_profile(profile)
            
            logger.info("Field added to profile", field=field, total_fields=len(profile))
            return len(profile)
        except Exception as e:
            logger.error("Failed to add field", field=field, error=str(e))
            raise

    def clear(self) -> None:
        """Clear all profile data."""
        try:
            self.save_profile({})
            logger.info("Profile cleared")
        except Exception as e:
            logger.error("Failed to clear profile", error=str(e))
            raise

    def get_field_names(self) -> list[str]:
        """Get list of profile field names ONLY (never values).
        
        Returns:
            Sorted list of field names
        """
        try:
            profile = self.load_profile()
            names = sorted(list(profile.keys()))
            logger.debug("Field names retrieved", count=len(names))
            return names
        except Exception as e:
            logger.error("Failed to get field names", error=str(e))
            return []

    async def map_fields(self, form_fields: list[dict]) -> dict:
        """Map form fields to profile fields using LLM.
        
        Args:
            form_fields: List of form field dicts with name, label, type, placeholder
            
        Returns:
            Dict with 'mappings' and 'confidence' keys
        """
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._map_fields_sync, form_fields)
        except Exception as e:
            logger.error("Failed to map fields", error=str(e))
            return {"mappings": {}, "confidence": {}}

    def _map_fields_sync(self, form_fields: list[dict]) -> dict:
        """Synchronous field mapping (runs in executor)."""
        profile = self.load_profile()
        profile_keys = list(profile.keys())
        
        mappings = {}
        confidence = {}
        
        for form_field in form_fields:
            field_name = form_field.get("name", "")
            label = form_field.get("label", "")
            field_type = form_field.get("type", "")
            placeholder = form_field.get("placeholder", "")
            
            # Build prompt
            prompt = f"""Given these profile keys: {profile_keys}
Form field: name={field_name} label={label} type={field_type} placeholder={placeholder}
Reply with ONLY the matching profile key name, or unknown"""
            
            try:
                # Call LLM
                llm = get_llm()
                response = llm.create_chat_completion(
                    messages=[{"role": "user", "content": prompt}]
                )
                
                reply = response["choices"][0]["message"]["content"].strip().lower()
                
                # Check for exact match
                matched_key = None
                conf = 0.0
                
                if reply == "unknown":
                    conf = 0.0
                else:
                    # Find best match
                    for key in profile_keys:
                        if key.lower() == reply:
                            matched_key = key
                            conf = 1.0
                            break
                    
                    # If no exact match, do fuzzy
                    if not matched_key and reply in "|".join(profile_keys).lower():
                        for key in profile_keys:
                            if reply in key.lower() or key.lower() in reply:
                                matched_key = key
                                conf = 0.8
                                break
                
                if matched_key:
                    mappings[field_name] = profile[matched_key]
                    confidence[field_name] = conf
                else:
                    confidence[field_name] = 0.0
                
                logger.debug(
                    "Field mapped",
                    form_field=field_name,
                    matched_key=matched_key,
                    confidence=conf
                )
            except Exception as e:
                logger.error("Failed to map single field", field_name=field_name, error=str(e))
                confidence[field_name] = 0.0
        
        logger.info("Fields mapped", total_fields=len(form_fields), matched=len(mappings))
        return {"mappings": mappings, "confidence": confidence}
