"""
Label Matching Agent using OpenAI Function Calling
Standardizes PDF form field names by matching to existing labels or creating new ones.
"""

import json
import os
from pathlib import Path
from openai import OpenAI
from rapidfuzz import fuzz, process
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Define input and output directories
INPUT_DIR = Path("2_fields_json")
OUTPUT_DIR = Path("4_standardized_output")
LABEL_LIST_PATH = Path("3_matching_labels/label_list.json")

# Create output directory if it doesn't exist
OUTPUT_DIR.mkdir(exist_ok=True)


class LabelMatchingAgent:
    """AI Agent for intelligent field label standardization"""
    
    def __init__(self, label_list_path, api_key=None):
        """
        Initialize the Label Matching Agent.
        
        Args:
            label_list_path: Path to the standardized label list JSON
            api_key: OpenAI API key (if not in environment)
        """
        self.client = OpenAI(api_key=api_key or os.getenv('OPENAI_API_KEY'))
        self.label_list_path = Path(label_list_path)
        self.label_list = self._load_label_list()
        self.original_label_count = len(self.label_list)
        
        # Track labels added during this session
        self.session_labels_added = []
        self.session_label_details = {}  # Store when/why labels were created
        
        # Track labels USED in current form (for uniqueness)
        self.current_form_labels = []  # All labels assigned to fields in current PDF
        self.current_form_label_count = {}  # Count usage of each label
        
    def _load_label_list(self):
        """Load existing standardized labels"""
        try:
            with open(self.label_list_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                labels = data.get('standardized_field_labels', [])
                print(f"Loaded {len(labels)} existing standardized labels")
                return labels
        except FileNotFoundError:
            print(f"Label list not found at {self.label_list_path}")
            return []
        except json.JSONDecodeError as e:
            print(f"Error loading label list: {e}")
            return []
    
    def _save_label_list(self):
        """Save updated label list back to file"""
        try:
            # Load existing file to preserve metadata
            with open(self.label_list_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Update labels (sorted and deduplicated)
            data['standardized_field_labels'] = sorted(set(self.label_list))
            
            # Update metadata
            if 'metadata' in data:
                data['metadata']['total_labels'] = len(self.label_list)
            
            # Save back
            with open(self.label_list_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            new_labels_added = len(self.label_list) - self.original_label_count
            if new_labels_added > 0:
                print(f"Updated label list: +{new_labels_added} new labels")
        except Exception as e:
            print(f"Error saving label list: {e}")
    
    def _is_descriptive(self, field_name):
        """
        Quick heuristic check if field name is already descriptive.
        
        Args:
            field_name: The field name to check
            
        Returns:
            bool: True if likely descriptive, False if gibberish
        """
        # Heuristics for "gibberish" XFA notation
        gibberish_indicators = [
            'topmostSubform',
            'BodyPage',
            '[0]',
            '[1]',
            '[2]',
            '.',  # Has dot notation (nested structure)
            'FLD[',
            'CB[',
        ]
        
        # If it has these patterns, it's gibberish
        if any(indicator in field_name for indicator in gibberish_indicators):
            return False
        
        # Check for common descriptive patterns
        descriptive_patterns = [
            'first_name', 'last_name', 'middle_name', 'full_name',
            'city', 'state', 'zip_code', 'address',
            'phone', 'email', 'date', 'signature',
            'ssn', 'social_security', 'medicare',
            'yes', 'no', 'checkbox', 'check'
        ]
        
        field_lower = field_name.lower()
        
        # If it contains descriptive patterns, it's likely descriptive
        if any(pattern in field_lower for pattern in descriptive_patterns):
            return True
        
        # If it's already snake_case and reasonable length, might be good
        if '_' in field_name and len(field_name) < 50 and field_name.replace('_', '').replace('[', '').replace(']', '').islower():
            return True
        
        # Check for Title Case descriptive names (like "Last Name", "City", "State")
        if field_name.istitle() and len(field_name.split()) <= 3 and not any(char in field_name for char in '[]().'):
            return True
            
        return False
    
    def _get_tools(self):
        """Define tools/functions available to the AI agent"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_similar_labels",
                    "description": "Search for labels similar to the given text in the standardized label list using fuzzy matching. Returns top matches with similarity scores (0-100).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "search_text": {
                                "type": "string",
                                "description": "The text to search for (from field context or field name)"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Number of top matches to return",
                                "default": 10
                            }
                        },
                        "required": ["search_text"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "check_label_exists",
                    "description": "Check if a specific label already exists in the standardized label list",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "description": "The exact label to check (case-sensitive)"
                            }
                        },
                        "required": ["label"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "check_label_used_in_form",
                    "description": "Check if a label has already been used for another field in THIS FORM. CRITICAL: Field names must be unique within a PDF!",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "description": "The label to check for uniqueness"
                            }
                        },
                        "required": ["label"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_numbered_variations",
                    "description": "Search for numbered variations of a label (e.g., 'marriage_date' -> find 'marriage_1_date', 'previous_marriage_1_date', etc.). Use this when you detect repeating patterns.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "base_label": {
                                "type": "string",
                                "description": "The base label to find variations of"
                            }
                        },
                        "required": ["base_label"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "validate_label_format",
                    "description": "Validate that a proposed label follows naming conventions before adding it. Use this before calling add_new_label.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "description": "The label to validate"
                            }
                        },
                        "required": ["label"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "add_new_label",
                    "description": "Add a newly created label to the standardized label list. Only call this after deciding to create a new label AND validating the format.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "description": "The new label in snake_case format (must be validated first)"
                            },
                            "reason": {
                                "type": "string",
                                "description": "Brief explanation for why this label was created"
                            }
                        },
                        "required": ["label", "reason"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "submit_final_decision",
                    "description": "Submit the final decision for field label standardization. Call this when you have made your decision.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["keep_original", "match_existing", "create_new"],
                                "description": "The action taken: keep_original (field name is descriptive), match_existing (found good match), or create_new (created new label)"
                            },
                            "original_field_name": {
                                "type": "string",
                                "description": "The original field name from PDF"
                            },
                            "standardized_label": {
                                "type": "string",
                                "description": "The final standardized label to use"
                            },
                            "confidence": {
                                "type": "integer",
                                "description": "Confidence score 0-100 for this decision",
                                "minimum": 0,
                                "maximum": 100
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "Brief explanation of why this decision was made"
                            }
                        },
                        "required": ["action", "original_field_name", "standardized_label", "confidence", "reasoning"]
                    }
                }
            }
        ]
    
    def _execute_tool(self, tool_name, tool_args):
        """
        Execute the requested tool and return results.
        
        Args:
            tool_name: Name of the tool to execute
            tool_args: Arguments for the tool
            
        Returns:
            dict: Tool execution results
        """
        if tool_name == "search_similar_labels":
            return self._search_similar(
                tool_args['search_text'], 
                tool_args.get('limit', 10)
            )
        
        elif tool_name == "validate_label_format":
            label = tool_args['label']
            is_valid, message = self._validate_label_format(label)
            return {
                "label": label,
                "is_valid": is_valid,
                "message": message,
                "validation_passed": is_valid
            }
        
        elif tool_name == "check_label_exists":
            exists = tool_args['label'] in self.label_list
            return {
                "exists": exists, 
                "label": tool_args['label'],
                "message": f"Label {'exists' if exists else 'does not exist'} in the list"
            }
        
        elif tool_name == "check_label_used_in_form":
            label = tool_args['label']
            already_used = label in self.current_form_labels
            usage_count = self.current_form_label_count.get(label, 0)
            
            return {
                "label": label,
                "already_used": already_used,
                "usage_count": usage_count,
                "message": f"Label '{label}' has been used {usage_count} time(s) in this form" if already_used 
                          else f"Label '{label}' is unique in this form"
            }
        
        elif tool_name == "search_numbered_variations":
            base_label = tool_args['base_label']
            
            # Search for variations with numbers
            import re
            variations = []
            
            # Patterns to search for:
            # - previous_marriage_1_date, previous_marriage_2_date
            # - marriage_1_date, marriage_2_date  
            # - marriage_date_1, marriage_date_2
            # - witness_1_signature, witness_2_signature
            
            for label in self.label_list:
                # Check if it contains the base label and a number
                if base_label.replace('_', '') in label.replace('_', ''):
                    # Check if it has numbers
                    if re.search(r'\d', label):
                        variations.append(label)
            
            return {
                "base_label": base_label,
                "variations_found": len(variations),
                "variations": variations[:15],  # Return first 15
                "suggestion": f"Found {len(variations)} numbered variations. Consider using these for repeating patterns."
            }
        
        elif tool_name == "add_new_label":
            label = tool_args['label']
            reason = tool_args.get('reason', 'No reason provided')
            
            # Validate format first
            is_valid, validation_msg = self._validate_label_format(label)
            if not is_valid:
                return {
                    "success": False,
                    "label": label,
                    "message": f"Label format invalid: {validation_msg}",
                    "validation_error": validation_msg
                }
            
            # Check if already in session (just added)
            if label in self.session_labels_added:
                return {
                    "success": False,
                    "label": label,
                    "message": f"Label '{label}' was already created earlier in this session. Use it directly.",
                    "created_when": self.session_label_details.get(label, {}).get('field_number', 'unknown')
                }
            
            # Check if already in master list
            if label in self.label_list:
                return {
                    "success": False,
                    "label": label,
                    "message": "Label already exists in the master list"
                }
            
            # Add new label
            self.label_list.append(label)
            self.session_labels_added.append(label)
            self.session_label_details[label] = {
                'reason': reason,
                'field_number': len(self.session_labels_added)
            }
            
            return {
                "success": True, 
                "label": label,
                "message": f"Successfully added new label: {label}",
                "reason": reason
            }
        
        elif tool_name == "submit_final_decision":
            return {
                "success": True,
                "decision": tool_args
            }
        
        return {"error": f"Unknown tool: {tool_name}"}
    
    def _validate_label_format(self, label):
        """
        Validate that a label follows naming conventions.
        
        Args:
            label: The label to validate
            
        Returns:
            tuple: (is_valid: bool, message: str)
        """
        import re
        
        # Check lowercase
        if label != label.lower():
            return False, "Label must be lowercase (found uppercase characters)"
        
        # Check for spaces
        if ' ' in label:
            return False, "Use underscores instead of spaces"
        
        # Check for invalid characters
        if not re.match(r'^[a-z][a-z0-9_]*$', label):
            return False, "Label must start with letter and contain only lowercase letters, numbers, and underscores"
        
        # Check length
        if len(label) < 2:
            return False, "Label too short (minimum 2 characters)"
        
        if len(label) > 80:
            return False, "Label too long (maximum 80 characters)"
        
        # Check for double underscores
        if '__' in label:
            return False, "Avoid double underscores"
        
        # Check start/end underscores
        if label.startswith('_') or label.endswith('_'):
            return False, "Label should not start or end with underscore"
        
        return True, "Valid label format"
    
    def _search_similar(self, search_text, limit):
        """
        Fuzzy search for similar labels.
        
        Args:
            search_text: Text to search for
            limit: Maximum number of results
            
        Returns:
            list: List of matching labels with similarity scores
        """
        if not search_text or not self.label_list:
            return []
        
        matches = process.extract(
            search_text, 
            self.label_list, 
            scorer=fuzz.token_sort_ratio,
            limit=min(limit, len(self.label_list))
        )
        
        return [
            {
                "label": match[0], 
                "similarity_score": round(match[1], 1),
                "interpretation": "excellent match" if match[1] >= 90 else
                                 "good match" if match[1] >= 75 else
                                 "possible match" if match[1] >= 60 else
                                 "weak match"
            } 
            for match in matches
        ]
    
    def match_field(self, field, verbose=True):
        """
        Main method: Match a field to a standardized label using AI agent.
        
        Args:
            field: Field dictionary with field_name, field_type, contexts, etc.
            verbose: Whether to print detailed progress
            
        Returns:
            dict: Decision with action, label, confidence, and reasoning
        """
        
        # Quick pre-check if field name is already descriptive
        is_descriptive = self._is_descriptive(field['field_name'])
        
        # Build system prompt for the agent
        system_prompt = """You are a government form field standardization expert. Your job is to standardize PDF form field names.

**Your Task:**
1. **If field_name is already descriptive** (like "first_name", "social_security_number", "wage_earner_ssn", "Last Name", "City"):
   - Keep it as is (convert to snake_case if needed)
   - Submit with action: "keep_original"

2. **If field_name is gibberish** (like "topmostSubform[0].BodyPage1[0].P1_Field[0]"):
   - Use field_context_on_pdf and field_context_detected to understand what the field represents
   - Search for similar labels using search_similar_labels tool
   - If you find a good match (similarity > 75% AND semantically correct): use it with action "match_existing"
   - If no good match exists: create a new descriptive label with action "create_new"

**CRITICAL CONTEXT PRIORITY RULES:**
- **ALWAYS prioritize field_context_on_pdf** (built-in PDF label) over field_context_detected (OCR text)
- **If field_name is descriptive** (like "Last Name", "City", "State"), use it even if detected context suggests something else
- **Only use field_context_detected** when field_name is gibberish AND field_context_on_pdf is empty/unhelpful
- **When field_context_detected conflicts with field_name**, trust the field_name if it's descriptive

**Label Creation Guidelines:**
- Use snake_case (lowercase with underscores) - REQUIRED
- Focus on SEMANTIC MEANING, not format (use "marriage_date" not "date_mm_dd_yyyy")
- Be descriptive but concise
- Common patterns:
  * Names: "first_name", "spouse_maiden_name", "wage_earner_name"
  * Dates: "date_of_birth", "marriage_date", "date_signed", "marriage_end_date"
  * SSN: "social_security_number", "spouse_ssn", "wage_earner_ssn"
  * Addresses: "mailing_address", "city", "state", "zip_code"
  * Checkboxes: add "_checkbox" suffix (e.g., "married_yes_checkbox", "marriage_performed_by_clergy_checkbox")
  * Numbers: "telephone_number", "employee_id"

**CRITICAL RULES - UNIQUENESS:**
- **Field names MUST be UNIQUE within a PDF!** Never assign the same label to multiple fields!
- ALWAYS check if a label was already used with check_label_used_in_form BEFORE assigning it
- If a label was already used, you MUST use a different label or add a distinguishing suffix

**CRITICAL RULES - REPEATING PATTERNS:**
- Look for context clues like "Marriage 1", "Marriage 2", "Witness 1", "Witness 2", "Previous Marriage number 1", etc.
- For repeating sections, use search_numbered_variations to find specific labels:
  * Example: "PREVIOUS MARRIAGE number 1" should use "previous_marriage_1_when" NOT generic "marriage_date"
  * Example: "PREVIOUS MARRIAGE number 2" should use "previous_marriage_2_when" NOT generic "marriage_date"
  * Example: "Witness 1" should use "signature_witness_1" NOT generic "witness_signature"
- If numbered variations don't exist, create them with numbers/context:
  * marriage_1_date, marriage_2_date
  * witness_1_address, witness_2_address
  * previous_marriage_1_spouse_name, previous_marriage_2_spouse_name

**CRITICAL RULES - GENERAL:**
- Before creating a new label, search existing labels thoroughly
- Search for numbered variations if you detect patterns (marriage 1, marriage 2, etc.)
- Validate labels using validate_label_format before adding
- Only match existing labels if they follow proper snake_case format
- Never match labels with Title Case, spaces, or special characters

**Process:**
1. Analyze the field information carefully - look for numbers/context (Marriage 1, Marriage 2, etc.)
2. **PRIORITIZE field_name if descriptive** (like "Last Name", "City", "State")
3. Use search_similar_labels to explore existing options
4. If you detect repeating patterns (1, 2, etc.), use search_numbered_variations
5. Choose best matching label
6. BEFORE deciding, check_label_used_in_form to ensure it's unique in this PDF
7. If label already used, find an alternative or create numbered version
8. If creating new:
   a. Validate with validate_label_format
   b. Check uniqueness with check_label_used_in_form
   c. If valid and unique, call add_new_label
   d. If invalid, fix the format and try again
9. Submit final decision with submit_final_decision

**Available Tools:**
- search_similar_labels: Find similar existing labels
- check_label_exists: Check if specific label exists  
- check_label_used_in_form: ⭐ NEW - Check if label already used in THIS PDF
- search_numbered_variations: ⭐ NEW - Find numbered versions (marriage_1_date, etc.)
- validate_label_format: Validate a proposed label before adding
- add_new_label: Add validated new label to the list
- submit_final_decision: Submit your final choice"""

        # Build user prompt with field details
        user_prompt = f"""Standardize this field:

**Field Name:** `{field['field_name']}`
**Field Type:** {field['field_type']}
**Context on PDF:** {field.get('field_context_on_pdf') or 'Not available'}
**Detected Context:** {field.get('field_context_detected') or 'Not available'}
**All Directions Context:** {field.get('field_context_all_directions', {})}
**Page:** {field.get('page', 'Unknown')}
**Position:** x={field['rect']['x0']:.1f}, y={field['rect']['y0']:.1f}

**Initial Assessment:** {"✓ Field name appears descriptive" if is_descriptive else "⚠ Field name appears to be internal XFA notation"}

**IMPORTANT:** If the field name is descriptive (like "Last Name", "City", "State"), prioritize it over detected context. Only use detected context when the field name is gibberish.

Analyze this field and use the available tools to make your decision. When ready, submit your final decision."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # Agent conversation loop
        final_decision = None
        max_iterations = 10  # Prevent infinite loops
        iteration = 0
        
        if verbose:
            print(f"  🤖 Agent analyzing field...")
        
        while iteration < max_iterations:
            iteration += 1
            
            try:
                response = self.client.chat.completions.create(
                    model="gpt-4o",  # or "gpt-4o-mini" for cost savings
                    messages=messages,
                    tools=self._get_tools(),
                    tool_choice="auto",
                    temperature=0.1  # Low temperature for consistency
                )
                
                assistant_message = response.choices[0].message
                
                # Add assistant response to conversation
                messages.append(assistant_message)
                
                # Check if agent wants to use tools
                if assistant_message.tool_calls:
                    # Execute each tool call
                    for tool_call in assistant_message.tool_calls:
                        tool_name = tool_call.function.name
                        tool_args = json.loads(tool_call.function.arguments)
                        
                        if verbose:
                            print(f"     → Using tool: {tool_name}")
                        
                        # Execute tool
                        tool_result = self._execute_tool(tool_name, tool_args)
                        
                        # Check if this is the final decision
                        if tool_name == "submit_final_decision":
                            final_decision = tool_result['decision']
                            break
                        
                        # Add tool result to conversation
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(tool_result)
                        })
                    
                    if final_decision:
                        break
                else:
                    # No tool calls - agent finished without decision
                    if verbose:
                        print("     ⚠ Agent finished without submitting decision")
                    break
                    
            except Exception as e:
                print(f"     ❌ Error during agent execution: {e}")
                break
        
        # If no decision was made, request explicitly
        if not final_decision:
            if verbose:
                print("     → Requesting explicit decision...")
            final_decision = self._request_explicit_decision(field, messages)
        
        return final_decision
    
    def _request_explicit_decision(self, field, conversation_history):
        """
        Fallback: Explicitly request decision if agent didn't submit.
        
        Args:
            field: The field being processed
            conversation_history: The conversation so far
            
        Returns:
            dict: The final decision
        """
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=conversation_history + [{
                    "role": "user",
                    "content": "Please submit your final decision using the submit_final_decision tool now."
                }],
                tools=self._get_tools(),
                tool_choice={"type": "function", "function": {"name": "submit_final_decision"}}
            )
            
            if response.choices[0].message.tool_calls:
                tool_call = response.choices[0].message.tool_calls[0]
                decision = json.loads(tool_call.function.arguments)
                return decision
        except Exception as e:
            print(f"     ❌ Error requesting explicit decision: {e}")
        
        # Ultimate fallback: keep original
        return {
            "action": "keep_original",
            "original_field_name": field['field_name'],
            "standardized_label": field['field_name'],
            "confidence": 0,
            "reasoning": "Agent failed to make decision - keeping original as fallback"
        }
    
    def process_pdf_fields(self, fields_json_path, output_path=None):
        """
        Process all fields from a PDF fields JSON file.
        
        Args:
            fields_json_path: Path to the extracted fields JSON
            output_path: Path to save results (auto-generated if None)
            
        Returns:
            dict: Processing results with summary and field decisions
        """
        
        # Reset form-level tracking for this new PDF
        self.current_form_labels = []
        self.current_form_label_count = {}
        
        # Load fields JSON
        fields_json_path = Path(fields_json_path)
        if not fields_json_path.exists():
            print(f"❌ Fields JSON not found: {fields_json_path}")
            return None
        
        with open(fields_json_path, 'r', encoding='utf-8') as f:
            pdf_data = json.load(f)
        
        # Auto-generate output path if not provided
        if output_path is None:
            output_filename = fields_json_path.stem.replace('_fields', '_standardized') + '.json'
            output_path = OUTPUT_DIR / output_filename
        
        # Initialize results
        results = {
            "filename": pdf_data['filename'],
            "source_file": str(fields_json_path),
            "summary": {
                "total_fields": pdf_data['total_fields'],
                "kept_original": 0,
                "matched_existing": 0,
                "created_new": 0,
                "labels_added": []
            },
            "fields": []
        }
        
        print(f"\n🚀 Processing {pdf_data['total_fields']} fields from {pdf_data['filename']}")
        print("=" * 80)
        
        # Process each field
        field_num = 0
        for page in pdf_data['pages']:
            for field in page['fields']:
                field_num += 1
                field_name_display = field['field_name'][:60] + "..." if len(field['field_name']) > 60 else field['field_name']
                print(f"\n[{field_num}/{pdf_data['total_fields']}] {field_name_display}")
                
                # Get agent decision
                decision = self.match_field(field, verbose=True)
                
                # Update summary
                action = decision['action']
                if action == 'keep_original':
                    results['summary']['kept_original'] += 1
                elif action == 'match_existing':
                    results['summary']['matched_existing'] += 1
                elif action == 'create_new':
                    results['summary']['created_new'] += 1
                    if decision['standardized_label'] not in results['summary']['labels_added']:
                        results['summary']['labels_added'].append(decision['standardized_label'])
                
                # Track label usage in this form
                assigned_label = decision['standardized_label']
                self.current_form_labels.append(assigned_label)
                self.current_form_label_count[assigned_label] = self.current_form_label_count.get(assigned_label, 0) + 1
                
                # Warn if duplicate detected
                if self.current_form_label_count[assigned_label] > 1:
                    print(f"  ⚠️  WARNING: Label '{assigned_label}' used {self.current_form_label_count[assigned_label]} times in this form!")
                    print(f"      Field names should be unique! Consider using numbered variations.")
                
                # Store result
                result_entry = {
                    **decision,
                    "field_type": field['field_type'],
                    "page": field['page'],
                    "original_contexts": {
                        "field_context_on_pdf": field.get('field_context_on_pdf'),
                        "field_context_detected": field.get('field_context_detected')
                    }
                }
                results['fields'].append(result_entry)
                
                # Print decision
                action_emoji = "✓" if action == "keep_original" else "🔗" if action == "match_existing" else "✨"
                print(f"  {action_emoji} Decision: {action.replace('_', ' ').title()}")
                print(f"  → Label: {decision['standardized_label']}")
                print(f"  → Confidence: {decision['confidence']}%")
                reasoning_display = decision['reasoning'][:100] + "..." if len(decision['reasoning']) > 100 else decision['reasoning']
                print(f"  → Reasoning: {reasoning_display}")
        
        # Save results
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        # Update label list file
        self._save_label_list()
        
        # Check for duplicate field names in this form
        duplicate_labels = {label: count for label, count in self.current_form_label_count.items() if count > 1}
        
        # Print final summary
        print("\n" + "=" * 80)
        print("📊 PROCESSING COMPLETE")
        print("=" * 80)
        print(f"✓ Kept Original:     {results['summary']['kept_original']:3d} fields")
        print(f"🔗 Matched Existing:  {results['summary']['matched_existing']:3d} fields")
        print(f"✨ Created New:       {results['summary']['created_new']:3d} fields")
        print(f"📝 New Labels Added:  {len(results['summary']['labels_added']):3d} labels")
        
        # Warn about duplicates
        if duplicate_labels:
            print(f"\n⚠️  DUPLICATE FIELD NAMES: {len(duplicate_labels)} label(s) used multiple times")
            print("   " + "=" * 76)
            for label, count in sorted(duplicate_labels.items()):
                print(f"   ⚠️  '{label}' assigned to {count} fields")
            print("   " + "=" * 76)
            print(f"\n   🚨 CRITICAL: PDFs require unique field names!")
            print(f"   ℹ️  The improved agent should now prevent this.")
            print(f"   💡 Delete the standardized JSON and re-run to fix:")
            print(f"      rm {output_path}")
            print(f"      python match_labels.py")
        
        if results['summary']['labels_added']:
            print("\n✨ New Labels Created:")
            for label in sorted(results['summary']['labels_added']):
                print(f"   • {label}")
        
        print(f"\n💾 Results saved to: {output_path}")
        print(f"📋 Label list updated: {self.label_list_path}")
        
        return results


def main():
    """Main execution function"""
    
    print("=" * 80)
    print("🤖 AI-POWERED LABEL MATCHING AGENT")
    print("=" * 80)
    
    # Check for OpenAI API key
    if not os.getenv('OPENAI_API_KEY'):
        print("\n❌ Error: OPENAI_API_KEY not found")
        print("Please make sure you have a .env file with:")
        print("  OPENAI_API_KEY=your-api-key-here")
        print("\nOr set it as an environment variable:")
        print("  export OPENAI_API_KEY='your-api-key'  # On Linux/Mac")
        print("  set OPENAI_API_KEY=your-api-key      # On Windows CMD")
        print("  $env:OPENAI_API_KEY='your-api-key'   # On Windows PowerShell")
        return
    
    # Check if input directory exists
    if not INPUT_DIR.exists():
        print(f"\n❌ Input directory '{INPUT_DIR}' not found!")
        return
    
    # Get all JSON files from input directory
    json_files = list(INPUT_DIR.glob("*_fields.json"))
    
    if not json_files:
        print(f"\n⚠️  No *_fields.json files found in '{INPUT_DIR}'")
        return
    
    print(f"\n📁 Found {len(json_files)} field file(s) to process:")
    for i, json_file in enumerate(json_files, 1):
        print(f"   {i}. {json_file.name}")
    
    # Initialize agent
    print(f"\n🔧 Initializing AI agent...")
    agent = LabelMatchingAgent(LABEL_LIST_PATH)
    
    # Process each file
    for json_file in json_files:
        print(f"\n" + "=" * 80)
        print(f"📄 Processing: {json_file.name}")
        print("=" * 80)
        
        try:
            results = agent.process_pdf_fields(json_file)
            if results:
                print(f"\n✅ Successfully processed {json_file.name}")
        except Exception as e:
            print(f"\n❌ Error processing {json_file.name}: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 80)
    print("✅ ALL FILES PROCESSED")
    print("=" * 80)


if __name__ == "__main__":
    main()

