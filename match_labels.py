

import google.generativeai as genai
import json
import os
import re
from pathlib import Path
from rapidfuzz import fuzz, process
from dotenv import load_dotenv

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
load_dotenv()

INPUT_DIR = Path("2_fields_json")
OUTPUT_DIR = Path("4_standardized_output")
LABEL_LIST_PATH = Path("3_matching_labels/label_list.json")
OUTPUT_DIR.mkdir(exist_ok=True)


class LabelMatchingAgent:
    """AI Agent for intelligent field label standardization using Gemini"""

    def __init__(self, label_list_path, api_key=None):
        genai.configure(api_key=api_key or os.getenv("GEMINI_API_KEY"))
        self.client = genai.GenerativeModel("gemini-2.5-flash")
        self.chat = self.client.start_chat(history=[])

        self.label_list_path = Path(label_list_path)
        self.label_list = self._load_label_list()
        self.original_label_count = len(self.label_list)

    # -------------------------------------------------------------------
    # Load / Save Label List
    # -------------------------------------------------------------------
    def _load_label_list(self):
        try:
            with open(self.label_list_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                labels = data.get("standardized_field_labels", [])
                print(f"Loaded {len(labels)} existing standardized labels")
                return labels
        except FileNotFoundError:
            print(f"Label list not found at {self.label_list_path}")
            return []
        except json.JSONDecodeError as e:
            print(f"Error loading label list: {e}")
            return []

    def _save_label_list(self):
        try:
            with open(self.label_list_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["standardized_field_labels"] = sorted(set(self.label_list))
            if "metadata" in data:
                data["metadata"]["total_labels"] = len(self.label_list)
            with open(self.label_list_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving label list: {e}")

    # -------------------------------------------------------------------
    # Label Validation & Normalization
    # -------------------------------------------------------------------
    def _validate_label_format(self, label):
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

    def _auto_fix_label(self, label):
        """Convert label into clean snake_case and apply semantic corrections safely."""
        original_label = label
        label = re.sub(r"([a-z])([A-Z])", r"\1_\2", label)
        label = re.sub(r"[^a-zA-Z0-9]+", "_", label).strip("_").lower()
        label = re.sub(r"_+", "_", label)

        # Safe semantic map (exact matches only)
        semantic_map = {
            "wage_earner_ssn": "wage_earner_social_security_number",
            "ssn": "social_security_number",
            "spouse_ssn": "spouse_social_security_number",
            "wage_earner": "wage_earner_name",
            "spouse": "spouse_name",
        }
        if label in semantic_map:
            label = semantic_map[label]

        # Automatically append "_checkbox" if field name implies checkbox
        checkbox_indicators = ["cb", "checkbox", "check", "yes", "no"]
        if any(ind in original_label.lower() for ind in checkbox_indicators):
            if not label.endswith("_checkbox"):
                label += "_checkbox"

        return label

    # -------------------------------------------------------------------
    # Heuristic: Detect Descriptive Names
    # -------------------------------------------------------------------
    def _is_descriptive(self, field_name):
        gibberish_indicators = [
            "topmostSubform",
            "BodyPage",
            "[0]",
            "[1]",
            "[2]",
            ".",
            "FLD[",
            "CB[",
        ]
        if any(ind in field_name for ind in gibberish_indicators):
            return False

        # Added checkbox-related patterns
        descriptive_patterns = [
            "first_name",
            "last_name",
            "middle_name",
            "full_name",
            "city",
            "state",
            "zip_code",
            "address",
            "phone",
            "email",
            "date",
            "signature",
            "ssn",
            "social_security",
            "yes",
            "no",
            "checkbox",
            "check",
        ]

        field_lower = field_name.lower()
        return any(p in field_lower for p in descriptive_patterns)

    # -------------------------------------------------------------------
    # Main Matching Logic
    # -------------------------------------------------------------------
    def match_field(self, field, verbose=True):
        system_prompt = """You are a PDF form field normalization expert.
Your job is to map each raw field name to a clear, standardized snake_case label.

Rules:
1️⃣ Always output in lowercase snake_case format.
2️⃣ Use concise semantic meaning — e.g.:
   - 'P1_WageEarnerSSN_FLD' → 'wage_earner_social_security_number'
   - 'FirstNameofSpouse' → 'spouse_first_name'
3️⃣ Never include page or index IDs (like P1_, [0], _FLD).
4️⃣ Only return valid JSON with keys:
   {action, original_field_name, standardized_label, confidence, reasoning}.
"""

        user_prompt = f"""Standardize this field:

Field Name: {field['field_name']}
Field Type: {field['field_type']}
Context on PDF: {field.get('field_context_on_pdf') or 'Not available'}
Detected Context: {field.get('field_context_detected') or 'Not available'}
Page: {field.get('page', 'Unknown')}
Position: {field['rect']['x0']:.1f}, {field['rect']['y0']:.1f}
"""

        if verbose:
            print("  🤖 Agent analyzing field...")

        try:
            conversation_text = "\n".join([
                f"SYSTEM: {system_prompt}",
                f"USER: {user_prompt}"
            ])
            response = self.chat.send_message(conversation_text)
            assistant_message = response.text.strip()

            if verbose:
                print(f"     🧠 Gemini Response Snippet: {assistant_message[:200]}...")

            # Extract and sanitize JSON
            json_match = re.search(r"\{.*\}", assistant_message, re.DOTALL)
            if not json_match:
                raise ValueError("No valid JSON found in response")

            json_str = json_match.group(0)

            # Clean invalid escape sequences
            json_str = (
                json_str
                .replace("\\.", "\\\\.")
                .replace("\\#", "\\\\#")
                .replace("\\(", "\\\\(")
                .replace("\\)", "\\\\)")
            )
            json_str = re.sub(r"\\(?![\"\\/bfnrtu])", r"\\\\", json_str)

            decision = json.loads(json_str)

            # Fix and validate label
            label = decision.get("standardized_label", "unknown")
            if label and label != "unknown":
                fixed_label = self._auto_fix_label(label)
                if fixed_label != label:
                    print(f"     🛠 Auto-fixed label format: {label} → {fixed_label}")
                    label = fixed_label
            valid, _ = self._validate_label_format(label)
            if not valid:
                label = self._auto_fix_label(label)
            decision["standardized_label"] = label

            # Normalize confidence
            conf = decision.get("confidence", 0)
            try:
                if isinstance(conf, str):
                    conf_map = {
                        "very high": 95,
                        "high": 90,
                        "medium": 70,
                        "low": 50,
                        "very low": 30,
                    }
                    conf = conf_map.get(conf.lower(), 90)
                elif isinstance(conf, float) and conf <= 1:
                    conf = round(conf * 100)
                conf = int(round(float(conf)))
            except Exception:
                conf = 90
            decision["confidence"] = conf

            print(f"  ⚙️ Decision: {decision.get('action', 'unknown').title()}")
            print(f"  → Label: {label}")
            print(f"  → Confidence: {conf}%")

            return decision

        except Exception as e:
            print(f"     ❌ Error during agent execution: {e}")
            return {
                "action": "keep_original",
                "original_field_name": field["field_name"],
                "standardized_label": field["field_name"],
                "confidence": 0,
                "reasoning": f"Error during analysis: {e}",
            }

    # -------------------------------------------------------------------
    # Process Fields JSON
    # -------------------------------------------------------------------
    def process_pdf_fields(self, fields_json_path, output_path=None):
        fields_json_path = Path(fields_json_path)
        with open(fields_json_path, "r", encoding="utf-8") as f:
            pdf_data = json.load(f)

        if output_path is None:
            output_filename = fields_json_path.stem.replace("_fields", "_standardized") + ".json"
            output_path = OUTPUT_DIR / output_filename

        print(f"\n🚀 Processing {pdf_data['total_fields']} fields from {pdf_data['filename']}")
        print("=" * 80)

        results = {"filename": pdf_data["filename"], "fields": []}
        for idx, page in enumerate(pdf_data["pages"], 1):
            for field in page["fields"]:
                print(f"\n[{len(results['fields']) + 1}/{pdf_data['total_fields']}] {field['field_name']}")
                decision = self.match_field(field, verbose=True)
                results["fields"].append(decision)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        self._save_label_list()
        print(f"\n✅ Processing complete.\n💾 Results saved to: {output_path}")
        return results


# -------------------------------------------------------------------
# Runner
# -------------------------------------------------------------------
def main():
    print("=" * 80)
    print("🤖 AI-POWERED LABEL MATCHING AGENT (Gemini Edition)")
    print("=" * 80)

    if not os.getenv("GEMINI_API_KEY"):
        print("❌ Missing GEMINI_API_KEY in environment.")
        return

    if not INPUT_DIR.exists():
        print(f"❌ Input directory '{INPUT_DIR}' not found.")
        return

    json_files = list(INPUT_DIR.glob("*_fields.json"))
    if not json_files:
        print(f"⚠️ No *_fields.json found in '{INPUT_DIR}'")
        return

    agent = LabelMatchingAgent(LABEL_LIST_PATH)
    for json_file in json_files:
        print(f"\n📄 Processing: {json_file.name}")
        agent.process_pdf_fields(json_file)

    print("\n✅ ALL FILES PROCESSED")
    print("=" * 80)


if __name__ == "__main__":
    main()
