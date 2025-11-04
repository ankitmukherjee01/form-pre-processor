"""
PDF Unlocker Script
Removes security restrictions from PDFs in the 0_locked_pdfs folder
and saves unlocked versions to the 1_unlocked_pdfs folder.
"""

import os
from pathlib import Path
import pikepdf

# Define input and output directories
INPUT_DIR = Path("0_locked_pdfs")
OUTPUT_DIR = Path("1_unlocked_pdfs")

# Create output directory if it doesn't exist
OUTPUT_DIR.mkdir(exist_ok=True)

def unlock_pdf(input_path, output_path, password=""):
    """
    Unlock a PDF file by removing security restrictions.
    
    Args:
        input_path: Path to the locked PDF
        output_path: Path where unlocked PDF will be saved
        password: Password for encrypted PDFs (empty string for no password)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Open the PDF (with password if needed)
        with pikepdf.open(input_path, password=password, allow_overwriting_input=True) as pdf:
            # Remove Adobe Usage Rights (Perms dictionary) - this is the main restriction!
            if pikepdf.Name.Perms in pdf.Root:
                del pdf.Root[pikepdf.Name.Perms]
                print(f"    Removed Adobe Usage Rights (Perms)")
            
            # Remove XFA (XML Forms Architecture) which can contain form restrictions
            if pikepdf.Name.AcroForm in pdf.Root:
                acroform = pdf.Root.AcroForm
                
                # Remove XFA - this often contains form field restrictions
                if pikepdf.Name.XFA in acroform:
                    del acroform[pikepdf.Name.XFA]
                    print(f"    Removed XFA form restrictions")
                
                # Remove SigFlags - signature-related flags
                if pikepdf.Name.SigFlags in acroform:
                    del acroform[pikepdf.Name.SigFlags]
                    print(f"    Removed signature flags")
                
                # Remove Lock from fields (if any)
                if pikepdf.Name.Fields in acroform:
                    def unlock_field(field):
                        """Recursively unlock a field and its children."""
                        # Remove Lock dictionary
                        lock_name = pikepdf.Name('/Lock')
                        if lock_name in field:
                            del field[lock_name]
                        
                        # Clear ReadOnly flag if set
                        if pikepdf.Name.Ff in field:
                            flags = int(field.Ff)
                            # Remove ReadOnly (bit 0) and Locked (bit 13)
                            flags = flags & ~1  # Clear ReadOnly
                            flags = flags & ~(1 << 13)  # Clear Locked
                            field[pikepdf.Name.Ff] = flags
                        
                        # Process children
                        if pikepdf.Name.Kids in field:
                            for kid in field.Kids:
                                unlock_field(kid)
                    
                    # Unlock all fields
                    for field in acroform.Fields:
                        unlock_field(field)
            
            # Save without encryption/restrictions
            pdf.save(output_path)
        return True
    except pikepdf.PasswordError:
        print(f"  ❌ Password required for: {input_path.name}")
        return False
    except Exception as e:
        print(f"  ❌ Error processing {input_path.name}: {str(e)}")
        return False

def main():
    """Main function to process all PDFs in the input directory."""
    
    # Check if input directory exists
    if not INPUT_DIR.exists():
        print(f"❌ Input directory '{INPUT_DIR}' not found!")
        return
    
    # Get all PDF files from input directory
    pdf_files = list(INPUT_DIR.glob("*.pdf"))
    
    if not pdf_files:
        print(f"No PDF files found in '{INPUT_DIR}'")
        return
    
    print(f"Found {len(pdf_files)} PDF file(s) to process...\n")
    
    success_count = 0
    failed_count = 0
    
    # Process each PDF file
    for pdf_file in pdf_files:
        print(f"Processing: {pdf_file.name}")
        
        output_path = OUTPUT_DIR / pdf_file.name
        
        # Try without password first
        if unlock_pdf(pdf_file, output_path):
            print(f"  ✓ Successfully unlocked: {pdf_file.name}")
            success_count += 1
        else:
            # If failed, try with user-provided password
            password = input(f"  Enter password for {pdf_file.name} (or press Enter to skip): ")
            if password:
                if unlock_pdf(pdf_file, output_path, password):
                    print(f"  ✓ Successfully unlocked with password: {pdf_file.name}")
                    success_count += 1
                else:
                    failed_count += 1
            else:
                print(f"  ⊘ Skipped: {pdf_file.name}")
                failed_count += 1
        
        print()
    
    # Print summary
    print("=" * 50)
    print(f"Processing complete!")
    print(f"  Successfully unlocked: {success_count}")
    print(f"  Failed/Skipped: {failed_count}")
    print(f"  Total processed: {len(pdf_files)}")
    print(f"\nUnlocked PDFs saved to: {OUTPUT_DIR.absolute()}")

if __name__ == "__main__":
    main()

