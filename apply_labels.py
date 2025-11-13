"""
Apply Standardized Labels to PDF
Takes unlocked PDFs and applies standardized field names from agent output.
This creates "refined" PDFs with clean, FLAT standardized field names.

Uses pikepdf with fuzzy matching to handle spacing differences between
PyMuPDF field extraction and pikepdf field names.
"""

import json
import pikepdf
from pathlib import Path
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Directory configuration
# ---------------------------------------------------------------------------
INPUT_DIR = Path("1_unlocked_pdfs")
OUTPUT_DIR = Path("5_refined_pdfs")
STANDARDIZED_DIR = Path("4_standardized_output")
FIELDS_DIR = Path("2_fields_json")

OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# LabelApplicator class
# ---------------------------------------------------------------------------
class LabelApplicator:
    """Applies standardized labels using pikepdf with fuzzy matching"""

    def __init__(self, pdf_path, standardized_json_path, fields_json_path):
        self.pdf_path = Path(pdf_path)
        self.json_path = Path(standardized_json_path)
        self.fields_json_path = Path(fields_json_path)
        self.field_mapping = {}
        self.stats = {
            'total_fields': 0,
            'renamed_fields': 0,
            'skipped_fields': 0,
            'errors': 0
        }

    # -----------------------------------------------------------------------
    # Load field mapping from JSON
    # -----------------------------------------------------------------------
    def load_mapping(self):
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for field_data in data.get('fields', []):
                original_name = field_data['original_field_name']
                standardized_label = field_data['standardized_label']
                self.field_mapping[original_name] = standardized_label

            self.stats['total_fields'] = len(self.field_mapping)
            print(f"[INFO] Loaded {self.stats['total_fields']} field mappings")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to load mapping: {e}")
            return False

    # -----------------------------------------------------------------------
    # Utility: normalize field names
    # -----------------------------------------------------------------------
    def _normalize_field_name(self, name):
        import re
        return re.sub(r'\s+', ' ', name.strip())

    # -----------------------------------------------------------------------
    # Utility: fuzzy match between names
    # -----------------------------------------------------------------------
    def _find_best_match(self, pikepdf_name):
        from rapidfuzz import fuzz

        normalized_pikepdf = self._normalize_field_name(pikepdf_name)
        best_match = None
        best_score = 0

        for original_name, standardized_label in self.field_mapping.items():
            normalized_original = self._normalize_field_name(original_name)
            score = fuzz.ratio(normalized_pikepdf, normalized_original)

            if score > best_score and score >= 95:  # High confidence threshold
                best_match = standardized_label
                best_score = score

        if best_match:
            print(f"      [FUZZY] '{pikepdf_name[:50]}...' -> '{best_match}' (score: {best_score})")

        return best_match

    # -----------------------------------------------------------------------
    # Apply standardized labels
    # -----------------------------------------------------------------------
    def apply_labels(self, output_path):
        print(f"\n[PROCESS] Processing: {self.pdf_path.name}")

        if not self.load_mapping():
            return False

        try:
            print(f"   Step 1: Opening PDF with pikepdf...")
            with pikepdf.open(self.pdf_path, allow_overwriting_input=False) as pdf:
                acroform = pdf.Root.AcroForm

                if not acroform or not acroform.get(pikepdf.Name.Fields):
                    print("   [WARNING] No AcroForm fields found.")
                    return False

                print(f"   Step 2: Collecting fields with full names...")
                field_widgets = []

                def collect_terminal_fields(field_obj):
                    # Recursively collect terminal fields (no kids)
                    if pikepdf.Name.Kids in field_obj:
                        for kid in field_obj.Kids:
                            collect_terminal_fields(kid)
                    else:
                        acro_field = pikepdf.AcroFormField(field_obj)
                        full_name = acro_field.fully_qualified_name
                        field_widgets.append((full_name, field_obj))

                for root_field in acroform.Fields:
                    collect_terminal_fields(root_field)

                print(f"   Found {len(field_widgets)} terminal fields")

                print(f"   Step 3: Renaming fields safely (in-place)...")
                for full_name, widget in field_widgets:
                    new_name = None

                    # Try exact match first
                    if full_name in self.field_mapping:
                        new_name = self.field_mapping[full_name]
                    else:
                        new_name = self._find_best_match(full_name)

                    if new_name:
                        try:
                            widget[pikepdf.Name.T] = pikepdf.String(new_name)
                            self.stats['renamed_fields'] += 1

                            if self.stats['renamed_fields'] <= 5:
                                print(f"      [RENAMED] {full_name} -> {new_name}")
                        except Exception as e:
                            print(f"      [ERROR] Failed to rename '{full_name}': {e}")
                            self.stats['errors'] += 1
                    else:
                        self.stats['skipped_fields'] += 1

                # ---------------------------------------------------------------
                # NEW FIX: Remove parent references after renaming
                # ---------------------------------------------------------------
                print(f"   Step 3.5: Removing parent references from renamed fields...")
                for _, widget in field_widgets:
                    try:
                        if pikepdf.Name.Parent in widget:
                            del widget[pikepdf.Name.Parent]
                    except Exception as e:
                        print(f"      [WARN] Failed to remove Parent from a field: {e}")

                # ---------------------------------------------------------------
                # Step 4: Flattening field hierarchy safely
                # ---------------------------------------------------------------
                print(f"   Step 4: Flattening field hierarchy safely...")
                try:
                    flat_fields = []

                    def collect_flat_fields(f):
                        if pikepdf.Name.Kids in f:
                            for kid in f.Kids:
                                collect_flat_fields(kid)
                        else:
                            flat_fields.append(f)

                    for f in acroform.Fields:
                        collect_flat_fields(f)

                    # Remove remaining parent refs for safety
                    for f in flat_fields:
                        if pikepdf.Name.Parent in f:
                            del f[pikepdf.Name.Parent]

                    acroform[pikepdf.Name.Fields] = flat_fields
                    print("   [INFO] Flattened and detached field hierarchy successfully.")
                except Exception as e:
                    print(f"   [WARNING] Could not fully flatten hierarchy: {e}")

                # ---------------------------------------------------------------
                # Step 5: Save the refined PDF
                # ---------------------------------------------------------------
                print(f"   Step 5: Saving refined PDF...")
                pdf.save(output_path)
                print(f"   [SUCCESS] Saved to: {output_path}")

            return True

        except Exception as e:
            print(f"   [ERROR] Error processing PDF: {e}")
            import traceback
            traceback.print_exc()
            return False

    # -----------------------------------------------------------------------
    # Print summary statistics
    # -----------------------------------------------------------------------
    def print_stats(self):
        print(f"\n   [STATS]")
        print(f"      Total fields in mapping: {self.stats['total_fields']}")
        print(f"      Fields renamed:          {self.stats['renamed_fields']}")
        print(f"      Fields skipped:          {self.stats['skipped_fields']}")
        print(f"      Errors:                  {self.stats['errors']}")


# ---------------------------------------------------------------------------
# Helper: find matching files
# ---------------------------------------------------------------------------
def find_matching_files():
    matches = []
    pdf_files = list(INPUT_DIR.glob("*.pdf"))

    for pdf_file in pdf_files:
        json_name = f"{pdf_file.stem}_standardized.json"
        json_path = STANDARDIZED_DIR / json_name

        fields_name = f"{pdf_file.stem}_fields.json"
        fields_path = FIELDS_DIR / fields_name

        if json_path.exists() and fields_path.exists():
            matches.append((pdf_file, json_path, fields_path))

    return matches


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------
def main():
    print("=" * 80)
    print("[LABEL APPLICATOR] APPLY STANDARDIZED LABELS TO PDFS")
    print("=" * 80)

    if not INPUT_DIR.exists():
        print(f"[ERROR] Input directory '{INPUT_DIR}' not found!")
        return

    print(f"\n[INFO] Searching for matching PDF and JSON files...")
    matches = find_matching_files()

    if not matches:
        print(f"\n[WARNING] No matching file triplets found!")
        print(f"   Expected: PDF + *_standardized.json + *_fields.json")
        return

    print(f"[SUCCESS] Found {len(matches)} matching file triplet(s):")
    for pdf_path, json_path, fields_path in matches:
        print(f"   [OK] {pdf_path.name} + {json_path.name} + {fields_path.name}")

    print("\n" + "=" * 80)
    print("[PROCESS] PROCESSING FILES")
    print("=" * 80)

    successful, failed = 0, 0

    for pdf_path, json_path, fields_path in matches:
        print(f"\n[PROCESS] Processing: {pdf_path.name}")
        output_filename = f"{pdf_path.stem}_refined.pdf"
        output_path = OUTPUT_DIR / output_filename

        try:
            applicator = LabelApplicator(pdf_path, json_path, fields_path)
            success = applicator.apply_labels(output_path)

            if success:
                applicator.print_stats()
                successful += 1
                print(f"\n[SUCCESS] Successfully processed {pdf_path.name}")
            else:
                failed += 1
                print(f"\n[ERROR] Failed to process {pdf_path.name}")

        except Exception as e:
            print(f"\n[ERROR] Error processing {pdf_path.name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 80)
    print("[SUMMARY] FINAL SUMMARY")
    print("=" * 80)
    print(f"[SUCCESS] Successfully processed: {successful} file(s)")
    if failed > 0:
        print(f"[FAILED] Failed:                 {failed} file(s)")

    print(f"\n[INFO] Refined PDFs saved to: {OUTPUT_DIR.absolute()}")

    if successful > 0:
        print(f"\n[SUCCESS] All done! Your PDFs now have standardized field names.")
        print(f"[INFO] Next steps:")
        print(f"   1. Run: python check_pdf_fields.py")
        print(f"   2. Verify all field names are standardized")
        print(f"   3. Use refined PDFs for your application")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()
