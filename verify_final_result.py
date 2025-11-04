#!/usr/bin/env python3
"""
Verify the final result - check field names and interactiveness
"""

import pikepdf
from pathlib import Path

def verify_final_result():
    """Verify that fields are renamed and interactive"""
    
    refined_path = Path("5_refined_pdfs/cms-40b-508c-2025_pdf_refined.pdf")
    
    print("=" * 80)
    print("VERIFYING FINAL RESULT")
    print("=" * 80)
    
    with pikepdf.open(refined_path) as pdf:
        acroform = pdf.Root.AcroForm
        fields = acroform.Fields
        
        print(f"Total fields in refined PDF: {len(fields)}")
        
        # Check the 3 previously problematic fields
        target_fields = [
            "volunteer_work_end_date",
            "dates_of_health_coverage_start_month", 
            "health_coverage_start_year_1"
        ]
        
        print(f"\nChecking the 3 previously problematic fields:")
        for field in fields:
            field_name = field.get(pikepdf.Name.T)
            if field_name in target_fields:
                print(f"\n✅ Found: {field_name}")
                
                # Check essential properties for interactiveness
                ft = field.get(pikepdf.Name.FT)
                ff = field.get(pikepdf.Name.Ff)
                v = field.get(pikepdf.Name.V)
                dv = field.get(pikepdf.Name.DV)
                maxlen = field.get(pikepdf.Name.MaxLen)
                
                print(f"   FT (Field Type): {ft}")
                print(f"   Ff (Field Flags): {ff}")
                print(f"   V (Value): {v}")
                print(f"   DV (Default Value): {dv}")
                print(f"   MaxLen: {maxlen}")
                
                # Check if it has interactive properties
                has_interactive = any([ft, ff, v, dv, maxlen])
                print(f"   Has Interactive Properties: {has_interactive}")
                
                if has_interactive:
                    print(f"   ✅ Field appears to be interactive!")
                else:
                    print(f"   ❌ Field may have lost interactiveness")
        
        # Show a few more renamed fields
        print(f"\nSample of renamed fields:")
        count = 0
        for field in fields:
            field_name = field.get(pikepdf.Name.T)
            if field_name and count < 10:
                print(f"   {field_name}")
                count += 1

if __name__ == "__main__":
    verify_final_result()
