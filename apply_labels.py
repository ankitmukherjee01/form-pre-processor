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

# Define input and output directories
INPUT_DIR = Path("1_unlocked_pdfs")
OUTPUT_DIR = Path("5_refined_pdfs")
STANDARDIZED_DIR = Path("4_standardized_output")
FIELDS_DIR = Path("2_fields_json")

# Create output directory if it doesn't exist
OUTPUT_DIR.mkdir(exist_ok=True)


class LabelApplicator:
    """Applies standardized labels using pikepdf with fuzzy matching for spacing differences"""
    
    def __init__(self, pdf_path, standardized_json_path, fields_json_path):
        """
        Initialize the Label Applicator.
        
        Args:
            pdf_path: Path to the unlocked PDF
            standardized_json_path: Path to the standardized labels JSON
            fields_json_path: Path to the original fields JSON (for field names)
        """
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
    
    def load_mapping(self):
        """Load the field mapping from standardized JSON"""
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Build mapping: original_field_name -> standardized_label
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
    
    def _normalize_field_name(self, name):
        """Normalize field name by collapsing multiple spaces"""
        import re
        return re.sub(r'\s+', ' ', name.strip())
    
    def _find_best_match(self, pikepdf_name):
        """Find best match for pikepdf field name using fuzzy matching"""
        from rapidfuzz import fuzz
        
        normalized_pikepdf = self._normalize_field_name(pikepdf_name)
        
        best_match = None
        best_score = 0
        
        for original_name, standardized_label in self.field_mapping.items():
            normalized_original = self._normalize_field_name(original_name)
            
            # Use ratio for overall similarity
            score = fuzz.ratio(normalized_pikepdf, normalized_original)
            
            if score > best_score and score >= 95:  # High confidence threshold
                best_match = standardized_label
                best_score = score
        
        if best_match:
            print(f"      [FUZZY] '{pikepdf_name[:50]}...' -> '{best_match}' (score: {best_score})")
        
        return best_match
    
    def apply_labels(self, output_path):
        """
        Apply standardized labels and flatten field hierarchy using pikepdf with fuzzy matching.
        
        Args:
            output_path: Path to save the refined PDF
            
        Returns:
            bool: Success status
        """
        print(f"\n[PROCESS] Processing: {self.pdf_path.name}")
        
        # Load mapping
        if not self.load_mapping():
            return False
        
        try:
            print(f"   Step 1: Opening PDF with pikepdf...")
            
            with pikepdf.open(self.pdf_path, allow_overwriting_input=False) as pdf:
                acroform = pdf.Root.AcroForm
                
                print(f"   Step 2: Collecting fields with full names...")
                
                # Collect all terminal field widgets with their full names
                field_widgets = []
                
                def collect_terminal_fields(field_obj):
                    if pikepdf.Name.Kids in field_obj:
                        for kid in field_obj.Kids:
                            collect_terminal_fields(kid)
                    else:
                        # Use fully_qualified_name to get complete field name
                        acro_field = pikepdf.AcroFormField(field_obj)
                        full_name = acro_field.fully_qualified_name
                        field_widgets.append((full_name, field_obj))
                
                for root_field in acroform.Fields:
                    collect_terminal_fields(root_field)
                
                print(f"   Found {len(field_widgets)} terminal widgets")
                
                print(f"   Step 3: Renaming fields and flattening hierarchy...")
                
                # Match fields by exact name and rename
                new_fields = []
                renamed_count = 0
                matched_widgets = set()
                
                for full_name, widget in field_widgets:
                    # Try exact match first
                    if full_name in self.field_mapping:
                        new_name = self.field_mapping[full_name]
                    else:
                        # Try fuzzy matching for spacing differences
                        new_name = self._find_best_match(full_name)
                    
                    if new_name:
                        # Create a new widget to preserve ALL properties
                        new_widget = pikepdf.Dictionary()
                        
                        # Copy ALL properties from original widget except Parent and Kids
                        for key, value in widget.items():
                            if key not in [pikepdf.Name.Parent, pikepdf.Name.Kids]:
                                new_widget[key] = value
                        
                        # Set the new field name (this is the key step!)
                        new_widget[pikepdf.Name.T] = pikepdf.String(new_name)
                        
                        new_fields.append(new_widget)
                        matched_widgets.add(full_name)
                        self.stats['renamed_fields'] += 1
                        renamed_count += 1
                        
                        # Show first few with debug info
                        if renamed_count <= 5:
                            orig_display = full_name[:55] + "..." if len(full_name) > 55 else full_name
                            print(f"      [SUCCESS] {orig_display}")
                            print(f"        -> {new_name}")
                            print(f"        [DEBUG] New widget T field: {new_widget.get(pikepdf.Name.T)}")
                        elif renamed_count == 6:
                            remaining = len(field_widgets) - 5
                            print(f"      [INFO] ... renaming {remaining} more fields")
                    else:
                        # Keep original - also create new widget to preserve properties
                        new_widget = pikepdf.Dictionary()
                        
                        # Copy ALL properties except Parent and Kids
                        for key, value in widget.items():
                            if key not in [pikepdf.Name.Parent, pikepdf.Name.Kids]:
                                new_widget[key] = value
                        
                        new_fields.append(new_widget)
                        self.stats['skipped_fields'] += 1
                
                # Replace hierarchical structure with flat array
                acroform[pikepdf.Name.Fields] = new_fields
                
                print(f"   Step 4: Saving refined PDF...")
                pdf.save(output_path)
                print(f"   [SUCCESS] Saved to: {output_path}")
            
            return True
            
        except Exception as e:
            print(f"   [ERROR] Error processing PDF: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def print_stats(self):
        """Print processing statistics"""
        print(f"\n   [STATS] Statistics:")
        print(f"      Total fields in mapping: {self.stats['total_fields']}")
        print(f"      Fields renamed:          {self.stats['renamed_fields']}")
        print(f"      Fields skipped:          {self.stats['skipped_fields']}")
        print(f"      Errors:                  {self.stats['errors']}")


def find_matching_files():
    """
    Find matching PDF, standardized JSON, and fields JSON files.
    
    Returns:
        list: List of (pdf_path, standardized_json_path, fields_json_path) tuples
    """
    matches = []
    
    # Get all PDFs in input directory
    pdf_files = list(INPUT_DIR.glob("*.pdf"))
    
    for pdf_file in pdf_files:
        # Look for matching standardized JSON
        json_name = f"{pdf_file.stem}_standardized.json"
        json_path = STANDARDIZED_DIR / json_name
        
        # Look for matching fields JSON
        fields_name = f"{pdf_file.stem}_fields.json"
        fields_path = FIELDS_DIR / fields_name
        
        if json_path.exists() and fields_path.exists():
            matches.append((pdf_file, json_path, fields_path))
    
    return matches


def main():
    """Main execution function"""
    
    print("=" * 80)
    print("[LABEL APPLICATOR] APPLY STANDARDIZED LABELS TO PDFS")
    print("=" * 80)
    
    # Check if input directory exists
    if not INPUT_DIR.exists():
        print(f"\n[ERROR] Input directory '{INPUT_DIR}' not found!")
        return
    
    # Find matching files
    print(f"\n[INFO] Searching for matching PDF and JSON files...")
    matches = find_matching_files()
    
    if not matches:
        print(f"\n[WARNING] No matching file triplets found!")
        print(f"   Looking for: PDF + *_standardized.json + *_fields.json")
        return
    
    print(f"[SUCCESS] Found {len(matches)} matching file triplet(s):")
    for pdf_path, json_path, fields_path in matches:
        print(f"   [OK] {pdf_path.name} + {json_path.name} + {fields_path.name}")
    
    print("\n" + "=" * 80)
    print("[PROCESS] PROCESSING FILES")
    print("=" * 80)
    
    successful = 0
    failed = 0
    
    # Process each file triplet
    for pdf_path, json_path, fields_path in matches:
        print(f"\n[PROCESS] Processing: {pdf_path.name}")
        
        # Generate output path
        output_filename = f"{pdf_path.stem}_refined.pdf"
        output_path = OUTPUT_DIR / output_filename
        
        try:
            # Create applicator and process
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
    
    # Final summary
    print("\n" + "=" * 80)
    print("[SUMMARY] FINAL SUMMARY")
    print("=" * 80)
    print(f"[SUCCESS] Successfully processed: {successful} file(s)")
    if failed > 0:
        print(f"[FAILED] Failed:                 {failed} file(s)")
    
    print(f"\n[INFO] Refined PDFs saved to: {OUTPUT_DIR.absolute()}")
    
    if successful > 0:
        print(f"\n[SUCCESS] Success! Your PDFs now have standardized field names and flattened hierarchy!")
        print(f"[INFO] Next steps:")
        print(f"   1. Run: python check_pdf_fields.py")
        print(f"   2. Verify all field names are standardized")
        print(f"   3. Use refined PDFs for your application")


if __name__ == "__main__":
    main()