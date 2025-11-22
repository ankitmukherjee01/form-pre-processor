

import os
import re
import json
import time
import math
import random
from pathlib import Path
from typing import List, Dict, Any, Optional

from rapidfuzz import process, fuzz
from dotenv import load_dotenv

# Optional Gemini client import — keep original style
try:
    import google.generativeai as genai
except Exception:
    genai = None

# ----------------------------
# Configuration
# ----------------------------
load_dotenv()

INPUT_DIR = Path("2_fields_json")
OUTPUT_DIR = Path("4_standardized_output")
LABEL_LIST_PATH = Path("3_matching_labels/label_list.json")
CACHE_PATH = Path("3_matching_labels/label_cache.json")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LABEL_LIST_PATH.parent.mkdir(parents=True, exist_ok=True)

# Batch size: number of fields sent per single Gemini request
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "8"))

# Max retries for transient errors (non-quota)
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))

# Backoff params for exponential backoff (base seconds)
BACKOFF_BASE = float(os.getenv("BACKOFF_BASE", "2.0"))

# Model to use — keep your previous model string
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ----------------------------
# Utility Functions
# ----------------------------
def safe_load_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        print(f"⚠️ Warning: Invalid JSON in {path}, starting fresh.")
        return {}

def safe_write_json(path: Path, obj: Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def sanitize_ai_response(text: str) -> str:
    """Remove code fences, thinking sections, control chars, and unwanted text."""
    if not isinstance(text, str):
        return ""

    # Remove markdown/json fences
    text = text.replace("```json", "").replace("```", "")
    # Remove labeled code fences like ```...``` with any language
    text = re.sub(r"```[a-zA-Z0-9_-]*\n", "", text)
    text = re.sub(r"\n```", "", text)

    # Remove "thinking" or internal commentary keys:
    text = re.sub(r'"thinking"\s*:\s*"(?:[^"\\]|\\.)*"\s*,?', "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"^\s*Assistant:\s*", "", text, flags=re.IGNORECASE)

    # Strip non-printables (control characters)
    text = re.sub(r"[\x00-\x1F\x7F]", "", text)

    # If assistant wrapped JSON inside explanatory text, try to extract bracketed JSON
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if match:
        text = match.group(0)

    return text.strip()

def parse_json_safe(json_text: str) -> Optional[Any]:
    """Attempt to parse JSON safely; return None on failure."""
    if not json_text:
        return None
    try:
        return json.loads(json_text)
    except Exception:
        # Try some progressive cleanups
        cleaned = json_text
        # fix stray single quotes (dangerous) — better to avoid but attempt common cases
        cleaned = cleaned.replace("'", '"')

        # Escape lone backslashes
        cleaned = re.sub(r'\\(?![\"\\/bfnrtu])', r'\\\\', cleaned)

        try:
            return json.loads(cleaned)
        except Exception:
            return None

# ----------------------------
# Label Agent Class
# ----------------------------
class LabelMatchingAgent:
    def __init__(self, label_list_path: Path, api_key: Optional[str] = None):
        self.label_list_path = Path(label_list_path)
        self.label_list = self._load_label_list()
        self.original_label_count = len(self.label_list)

        # Load cache
        self.cache = safe_load_json(CACHE_PATH) or {}

        # Configure Gemini if available
        if genai is not None:
            api_key = api_key or os.getenv("GEMINI_API_KEY")
            if api_key:
                genai.configure(api_key=api_key)
                try:
                    self.client = genai.GenerativeModel(GEMINI_MODEL)
                    # chat object for streaming style if desired
                    self.chat = self.client.start_chat(history=[])
                except Exception as e:
                    print(f"⚠️ Gemini client initialization failed: {e}")
                    self.client = None
                    self.chat = None
            else:
                print("⚠️ GEMINI_API_KEY not provided. Will use local fallback only.")
                self.client = None
                self.chat = None
        else:
            print("⚠️ google.generativeai is not available in this environment.")
            self.client = None
            self.chat = None

    # ----------------------------
    # Label list handling
    # ----------------------------
    def _load_label_list(self) -> List[str]:
        data = safe_load_json(self.label_list_path)
        labels = data.get("standardized_field_labels", [])
        print(f"Loaded {len(labels)} existing standardized labels")
        return labels

    def _save_label_list(self):
        data = safe_load_json(self.label_list_path)
        data["standardized_field_labels"] = sorted(set(self.label_list))
        data.setdefault("metadata", {})
        data["metadata"]["total_labels"] = len(self.label_list)
        safe_write_json(self.label_list_path, data)

    # ----------------------------
    # Label format helpers (kept & improved)
    # ----------------------------
    def _validate_label_format(self, label: str):
        if not isinstance(label, str):
            return False, "Not a string"
        if label != label.lower():
            return False, "Label must be lowercase"
        if " " in label:
            return False, "Use underscores instead of spaces"
        if not re.match(r"^[a-z][a-z0-9_]*$", label):
            return False, "Invalid characters"
        if len(label) < 2 or len(label) > 80:
            return False, "Invalid length"
        if "__" in label or label.startswith("_") or label.endswith("_"):
            return False, "Avoid underscores at edges or double underscores"
        return True, "Valid"

    def _auto_fix_label(self, label: str) -> str:
        if not isinstance(label, str):
            label = str(label)

        original_label = label
        # Insert underscores before camel case boundaries
        label = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", label)
        # Replace non-alphanumerics with underscore
        label = re.sub(r"[^a-zA-Z0-9]+", "_", label)
        # lower
        label = label.strip("_").lower()
        # collapse multiple underscores
        label = re.sub(r"_+", "_", label)

        # semantic map (extend as needed)
        semantic_map = {
            "wage_earner_ssn": "wage_earner_social_security_number",
            "ssn": "social_security_number",
            "spouse_ssn": "spouse_social_security_number",
            "wage_earner": "wage_earner_name",
            "spouse": "spouse_name",
            "yes": "yes_checkbox",
            "no": "no_checkbox",
        }
        if label in semantic_map:
            label = semantic_map[label]

        # If original label contained checkbox cues, append _checkbox
        checkbox_indicators = ["cb", "checkbox", "check", "yes", "no", "tick"]
        if any(ind in original_label.lower() for ind in checkbox_indicators):
            if not label.endswith("_checkbox"):
                label = label + "_checkbox"

        return label

    def _is_descriptive(self, field_name: str):
        if not isinstance(field_name, str):
            return False
        gibberish_indicators = ["topmostSubform", "BodyPage", "[0]", "[1]", "[2]", "FLD[", "CB["]
        if any(ind in field_name for ind in gibberish_indicators):
            return False

        descriptive_patterns = [
            "first_name", "last_name", "middle_name", "full_name", "city", "state", "zip_code",
            "address", "phone", "email", "date", "signature", "ssn", "social_security",
            "yes", "no", "checkbox", "check"
        ]
        field_lower = field_name.lower()
        return any(p in field_lower for p in descriptive_patterns)

    # ----------------------------
    # Local fuzzy-matching fallback
    # ----------------------------
    def fuzzy_match_local(self, raw: str) -> Dict[str, Any]:
        """Try to match against known labels in label_list using rapidfuzz.
           If none found, generate a cleaned candidate via _auto_fix_label().
        """
        if not raw:
            return {
                "action": "keep_original",
                "original_field_name": raw,
                "standardized_label": raw,
                "confidence": 30,
                "reasoning": "Empty field name"
            }

        candidates = self.label_list or []
        best_label = None
        best_score = 0
        if candidates:
            best = process.extractOne(raw, candidates, scorer=fuzz.token_sort_ratio)
            if best:
                best_label, best_score = best[0], int(best[1])

        if best_score >= 80:
            # strong match found
            return {
                "action": "use_existing",
                "original_field_name": raw,
                "standardized_label": best_label,
                "confidence": int(best_score),
                "reasoning": f"Matched by fuzzy to existing label '{best_label}'"
            }

        # No strong match — auto fix
        fixed = self._auto_fix_label(raw)
        valid, reason = self._validate_label_format(fixed)
        conf = 75 if valid else 50
        return {
            "action": "auto_fix",
            "original_field_name": raw,
            "standardized_label": fixed,
            "confidence": conf,
            "reasoning": f"Auto-fixed label from raw name. Validation: {reason}"
        }

    # ----------------------------
    # Build system + user prompt for a batch
    # ----------------------------
    def _build_batch_prompt(self, fields: List[Dict[str, Any]]) -> str:
        """
        Instruct the model to return a JSON array where each item corresponds to a field:
        [
          {"action":"use_existing","original_field_name":"...","standardized_label":"...","confidence":90,"reasoning":"..."},
          ...
        ]
        """
        system_prompt = (
            "You are a PDF form field normalization expert.\n"
            "Map each raw field name to a concise standardized snake_case label.\n"
            "Rules:\n"
            "  - Output only valid JSON (an array) with one object per field in the same order.\n"
            "  - Each object keys: action, original_field_name, standardized_label, confidence, reasoning\n"
            "  - Use lowercase snake_case. Remove page/index tokens like P1_, [0], _FLD, etc.\n"
            "  - For checkboxes, append _checkbox to the label.\n"
            "  - Confidence should be a number 0-100.\n"
            "Return the array only — no extra commentary or markdown fences.\n"
        )
        # Provide the fields compactly
        user_lines = []
        for f in fields:
            # include context if present
            ctx = f.get("field_context_on_pdf") or f.get("field_context_detected") or ""
            user_lines.append(
                json.dumps({
                    "field_name": f.get("field_name"),
                    "field_type": f.get("field_type"),
                    "page": f.get("page", "Unknown"),
                    "position": f.get("rect", {}),
                    "context": ctx
                }, ensure_ascii=False)
            )
        user_prompt = "Standardize these fields (one JSON object per input, in the same order):\n" + "\n".join(user_lines)
        return system_prompt + "\n\n" + user_prompt

    # ----------------------------
    # Send batch to Gemini with retry/backoff and parse result
    # ----------------------------
    def _call_gemini_with_retry(self, prompt: str) -> Optional[Any]:
        if not self.chat or not genai:
            return None

        attempt = 0
        while True:
            attempt += 1
            try:
                response = self.chat.send_message(prompt)
                raw_text = getattr(response, "text", "") or str(response)
                sanitized = sanitize_ai_response(raw_text)
                if not sanitized:
                    return None
                parsed = parse_json_safe(sanitized)
                if parsed is None:
                    # final attempt to salvage by trying to extract first JSON block
                    m = re.search(r"(\[.*\])", sanitized, re.DOTALL)
                    if m:
                        parsed = parse_json_safe(m.group(1))
                return parsed
            except Exception as exc:
                msg = str(exc)
                # 429 quota handling — check for retry_delay in message
                if "429" in msg or "quota" in msg.lower():
                    # try to extract seconds from "retry_delay" or allow exponential with jitter
                    match = re.search(r"retry_delay[^0-9]*(\d+)", msg)
                    if match:
                        wait = int(match.group(1)) + 1
                    else:
                        # exponential backoff fallback
                        wait = int(BACKOFF_BASE * (2 ** (attempt - 1))) + random.randint(0, 3)
                    print(f"⚠️ Gemini quota or rate-limit hit. Waiting {wait}s then retry (attempt {attempt})")
                    time.sleep(wait)
                    continue
                # transient network etc.
                if attempt < MAX_RETRIES:
                    wait = int(BACKOFF_BASE * (2 ** (attempt - 1))) + random.randint(0, 2)
                    print(f"⚠️ Gemini call failed (attempt {attempt}/{MAX_RETRIES}): {exc}. Backing off {wait}s")
                    time.sleep(wait)
                    continue
                print(f"❌ Gemini failed after {attempt} attempts: {exc}")
                return None

    # ----------------------------
    # Process a single batch of fields
    # ----------------------------
    def process_batch(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        fields: list of field dicts (same structure as your page["fields"] items)
        returns: list of decision dicts in the same order
        """
        decisions = []
        # first check cache and local fuzzy for each item
        to_call = []
        indices_to_call = []
        for idx, f in enumerate(fields):
            key = f"{f.get('field_name')}|{f.get('field_type')}|{f.get('page', '')}"
            if key in self.cache:
                decisions.append(self.cache[key])
            else:
                # add placeholder to maintain ordering
                decisions.append(None)
                to_call.append(f)
                indices_to_call.append(idx)

        if to_call and self.chat:
            prompt = self._build_batch_prompt(to_call)
            parsed = self._call_gemini_with_retry(prompt)
            if parsed and isinstance(parsed, list) and len(parsed) == len(to_call):
                # accept results, sanitize each item
                for out_obj, original_field, idx in zip(parsed, to_call, indices_to_call):
                    # normalize keys
                    if not isinstance(out_obj, dict):
                        # fallback: use local fuzzy
                        decision = self.fuzzy_match_local(original_field.get("field_name"))
                    else:
                        decision = {
                            "action": out_obj.get("action", "ai_suggest"),
                            "original_field_name": out_obj.get("original_field_name", original_field.get("field_name")),
                            "standardized_label": out_obj.get("standardized_label", original_field.get("field_name")),
                            "confidence": int(out_obj.get("confidence", 90)) if str(out_obj.get("confidence", "")).isdigit() else out_obj.get("confidence", 90),
                            "reasoning": out_obj.get("reasoning", "")
                        }

                        # auto-fix label format & validate
                        label = decision["standardized_label"]
                        label_fixed = self._auto_fix_label(label)
                        if label_fixed != label:
                            decision["reasoning"] = decision.get("reasoning", "") + f" | auto-fixed {label} → {label_fixed}"
                        # validate
                        valid, reason = self._validate_label_format(label_fixed)
                        if not valid:
                            label_fixed = self._auto_fix_label(label_fixed)
                        decision["standardized_label"] = label_fixed

                        # normalize confidence
                        try:
                            conf = decision.get("confidence", 90)
                            if isinstance(conf, str):
                                confmap = {"very high":95,"high":90,"medium":70,"low":50,"very low":30}
                                conf = confmap.get(conf.lower(), 80)
                            elif isinstance(conf, float) and conf <= 1.0:
                                conf = int(round(conf * 100))
                            conf = int(max(0, min(100, int(conf))))
                        except Exception:
                            conf = 80
                        decision["confidence"] = conf

                    decisions[idx] = decision
                    # cache
                    cache_key = f"{original_field.get('field_name')}|{original_field.get('field_type')}|{original_field.get('page','')}"
                    self.cache[cache_key] = decision

            else:
                # Gemini failed or returned unexpected shape — fallback to local fuzzy for these
                print("⚠️ Gemini returned no usable result for this batch — using local fuzzy fallback.")
                for original_field, idx in zip(to_call, indices_to_call):
                    decision = self.fuzzy_match_local(original_field.get("field_name"))
                    decisions[idx] = decision
                    cache_key = f"{original_field.get('field_name')}|{original_field.get('field_type')}|{original_field.get('page','')}"
                    self.cache[cache_key] = decision
        else:
            # No gemini available — fallback to local for remaining
            for original_field, idx in zip(to_call, indices_to_call):
                decision = self.fuzzy_match_local(original_field.get("field_name"))
                decisions[idx] = decision
                cache_key = f"{original_field.get('field_name')}|{original_field.get('field_type')}|{original_field.get('page','')}"
                self.cache[cache_key] = decision

        return decisions

    # ----------------------------
    # Process entire PDF fields JSON
    # ----------------------------
    def process_pdf_fields(self, fields_json_path: Path, output_path: Optional[Path] = None):
        fields_json_path = Path(fields_json_path)
        pdf_data = safe_load_json(fields_json_path)
        if not pdf_data:
            print(f"⚠️ Skipping unreadable or empty JSON: {fields_json_path}")
            return None

        if output_path is None:
            output_filename = fields_json_path.stem.replace("_fields", "_standardized") + ".json"
            output_path = OUTPUT_DIR / output_filename

        total_fields = pdf_data.get("total_fields", 0)
        print(f"\n🚀 Processing {total_fields} fields from {pdf_data.get('filename', fields_json_path.name)}")
        print("=" * 80)

        all_fields = []
        # flatten page-wise fields preserving order
        for page in pdf_data.get("pages", []):
            for f in page.get("fields", []):
                all_fields.append(f)

        results = {"filename": pdf_data.get("filename", fields_json_path.name), "fields": []}
        # process in batches
        for start in range(0, len(all_fields), BATCH_SIZE):
            batch = all_fields[start:start+BATCH_SIZE]
            print(f"\nProcessing batch {start//BATCH_SIZE + 1} — fields {start+1} to {start+len(batch)}")
            batch_decisions = self.process_batch(batch)
            # append each decision and print short logs
            for dec in batch_decisions:
                # ensure structure consistent
                dec.setdefault("original_field_name", dec.get("original_field_name", ""))
                dec.setdefault("standardized_label", dec.get("standardized_label", dec.get("original_field_name")))
                dec.setdefault("confidence", int(dec.get("confidence", 0)))
                dec.setdefault("reasoning", dec.get("reasoning", ""))
                results["fields"].append(dec)
                print(f"  → {dec['original_field_name']}  =>  {dec['standardized_label']}  ({dec['confidence']}%)")

        # save output
        safe_write_json(output_path, results)
        # persist cache and label list
        safe_write_json(CACHE_PATH, self.cache)

        # Add any newly discovered labels to label_list
        for dec in results["fields"]:
            lbl = dec.get("standardized_label")
            if lbl and lbl not in self.label_list:
                self.label_list.append(lbl)
        self._save_label_list()

        print(f"\n✅ Processing complete. Results saved to: {output_path}")
        return results

# ----------------------------
# Runner
# ----------------------------
def main():
    print("=" * 80)
    print("🤖 AI-POWERED LABEL MATCHING AGENT (Optimized Gemini + Fuzzy Fallback)")
    print("=" * 80)

    # Validate input dir
    if not INPUT_DIR.exists():
        print(f"❌ Input directory '{INPUT_DIR}' not found.")
        return

    json_files = list(INPUT_DIR.glob("*_fields.json"))
    if not json_files:
        print(f"⚠️ No *_fields.json found in '{INPUT_DIR}'")
        return

    # instantiate agent
    agent = LabelMatchingAgent(LABEL_LIST_PATH)

    for json_file in json_files:
        print(f"\n📄 Processing file: {json_file.name}")
        agent.process_pdf_fields(json_file)

    print("\n✅ ALL FILES PROCESSED")
    print("=" * 80)

if __name__ == "__main__":
    main()
