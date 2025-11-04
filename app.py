#!/usr/bin/env python3
"""
TempoDyn Pre-Processor - Complete Pipeline Orchestrator
Processes PDFs through the entire pipeline: unlock → extract → match → apply
"""

import os
import sys
import json
import time
from pathlib import Path
from typing import List, Tuple, Optional
import argparse
from datetime import datetime

# Import our pipeline modules
from unlock_pdfs import main as unlock_main, INPUT_DIR as UNLOCK_INPUT_DIR, OUTPUT_DIR as UNLOCK_OUTPUT_DIR
from extract_fields import main as extract_main, INPUT_DIR as EXTRACT_INPUT_DIR, OUTPUT_DIR as EXTRACT_OUTPUT_DIR
from match_labels import LabelMatchingAgent, INPUT_DIR as MATCH_INPUT_DIR, OUTPUT_DIR as MATCH_OUTPUT_DIR, LABEL_LIST_PATH
from apply_labels import LabelApplicator, INPUT_DIR as APPLY_INPUT_DIR, OUTPUT_DIR as APPLY_OUTPUT_DIR, STANDARDIZED_DIR as APPLY_STANDARDIZED_DIR


class PipelineOrchestrator:
    """Orchestrates the complete PDF processing pipeline"""
    
    def __init__(self, verbose: bool = True):
        """
        Initialize the pipeline orchestrator.
        
        Args:
            verbose: Whether to print detailed progress information
        """
        self.verbose = verbose
        self.start_time = None
        self.stats = {
            'total_pdfs': 0,
            'successful_pdfs': 0,
            'failed_pdfs': 0,
            'skipped_pdfs': 0,
            'processing_times': {},
            'errors': []
        }
        
    def log(self, message: str, level: str = "INFO"):
        """Print log message with timestamp"""
        if not self.verbose:
            return
            
        timestamp = datetime.now().strftime("%H:%M:%S")
        level_emoji = {
            "INFO": "[INFO]",
            "SUCCESS": "[SUCCESS]", 
            "WARNING": "[WARNING]",
            "ERROR": "[ERROR]",
            "PROGRESS": "[PROGRESS]"
        }.get(level, "[LOG]")
        
        print(f"[{timestamp}] {level_emoji} {message}")
    
    def cleanup_temp_files(self):
        """Clean up any temporary files that might have been created"""
        try:
            # Look for temp files in the input directory
            temp_files = list(UNLOCK_INPUT_DIR.glob("temp_*.pdf"))
            for temp_file in temp_files:
                if temp_file.exists():
                    temp_file.unlink()
                    self.log(f"Cleaned up temporary file: {temp_file.name}", "INFO")
        except Exception as e:
            self.log(f"Error during cleanup: {e}", "WARNING")
    
    def check_prerequisites(self) -> bool:
        """Check if all prerequisites are met"""
        self.log("Checking prerequisites...", "PROGRESS")
        
        # Clean up any leftover temp files first
        self.cleanup_temp_files()
        
        # Check directories exist
        required_dirs = [
            UNLOCK_INPUT_DIR,
            UNLOCK_OUTPUT_DIR,
            EXTRACT_OUTPUT_DIR,
            MATCH_OUTPUT_DIR,
            APPLY_OUTPUT_DIR,
            APPLY_STANDARDIZED_DIR
        ]
        
        for dir_path in required_dirs:
            if not dir_path.exists():
                self.log(f"Creating directory: {dir_path}", "INFO")
                dir_path.mkdir(parents=True, exist_ok=True)
        
        # Check OpenAI API key
        if not os.getenv('OPENAI_API_KEY'):
            self.log("OPENAI_API_KEY not found in environment", "ERROR")
            self.log("Please set your OpenAI API key:", "INFO")
            self.log("  export OPENAI_API_KEY='your-api-key'  # Linux/Mac", "INFO")
            self.log("  set OPENAI_API_KEY=your-api-key      # Windows CMD", "INFO")
            self.log("  $env:OPENAI_API_KEY='your-api-key'   # Windows PowerShell", "INFO")
            return False
        
        # Check label list exists
        if not LABEL_LIST_PATH.exists():
            self.log(f"Label list not found: {LABEL_LIST_PATH}", "ERROR")
            self.log("Please ensure the label list file exists", "INFO")
            return False
        
        self.log("All prerequisites met!", "SUCCESS")
        return True
    
    def get_pdfs_to_process(self) -> List[Path]:
        """Get list of PDFs that need processing"""
        pdf_files = list(UNLOCK_INPUT_DIR.glob("*.pdf"))
        
        if not pdf_files:
            self.log(f"No PDF files found in {UNLOCK_INPUT_DIR}", "WARNING")
            return []
        
        # Filter out already processed PDFs
        pdfs_to_process = []
        for pdf_file in pdf_files:
            # Check if already processed (refined PDF exists)
            refined_pdf = APPLY_OUTPUT_DIR / f"{pdf_file.stem}_refined.pdf"
            if refined_pdf.exists():
                self.log(f"Skipping {pdf_file.name} - already processed", "WARNING")
                self.stats['skipped_pdfs'] += 1
            else:
                pdfs_to_process.append(pdf_file)
        
        self.stats['total_pdfs'] = len(pdfs_to_process)
        return pdfs_to_process
    
    def stage_unlock_pdfs(self, pdf_files: List[Path]) -> bool:
        """Stage 1: Unlock PDFs"""
        if not pdf_files:
            self.log("No PDFs to unlock", "WARNING")
            return True
        
        self.log(f"Stage 1: Unlocking {len(pdf_files)} PDF(s)...", "PROGRESS")
        
        try:
            # Import the unlock function directly to avoid modifying the directory
            from unlock_pdfs import unlock_pdf
            
            success_count = 0
            failed_count = 0
            
            # Process each PDF individually
            for pdf_file in pdf_files:
                self.log(f"Unlocking {pdf_file.name}...", "INFO")
                output_path = UNLOCK_OUTPUT_DIR / pdf_file.name
                
                if unlock_pdf(pdf_file, output_path):
                    self.log(f"Successfully unlocked {pdf_file.name}", "SUCCESS")
                    success_count += 1
                else:
                    self.log(f"Failed to unlock {pdf_file.name}", "ERROR")
                    failed_count += 1
            
            if success_count > 0:
                self.log(f"Stage 1 completed: {success_count} successful, {failed_count} failed", "SUCCESS")
                return failed_count == 0
            else:
                self.log("Stage 1 failed: No PDFs were unlocked", "ERROR")
                return False
            
        except Exception as e:
            self.log(f"Stage 1 failed: {e}", "ERROR")
            self.stats['errors'].append(f"Unlock stage: {e}")
            return False
    
    def stage_extract_fields(self, pdf_files: List[Path]) -> bool:
        """Stage 2: Extract field information"""
        self.log("Stage 2: Extracting field information...", "PROGRESS")
        
        try:
            # Import the extract function directly
            from extract_fields import extract_fields_from_pdf
            
            success_count = 0
            total_fields = 0
            
            # Process each unlocked PDF individually
            for pdf_file in pdf_files:
                unlocked_pdf = UNLOCK_OUTPUT_DIR / pdf_file.name
                if not unlocked_pdf.exists():
                    self.log(f"Unlocked PDF not found: {unlocked_pdf}", "ERROR")
                    continue
                
                self.log(f"Extracting fields from {pdf_file.name}...", "INFO")
                
                pdf_data = extract_fields_from_pdf(unlocked_pdf)
                
                if 'error' in pdf_data:
                    self.log(f"Error extracting from {pdf_file.name}: {pdf_data['error']}", "ERROR")
                    continue
                
                # Save JSON file
                output_file = EXTRACT_OUTPUT_DIR / f"{pdf_file.stem}_fields.json"
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(pdf_data, f, indent=2, ensure_ascii=False)
                
                self.log(f"Extracted {pdf_data['total_fields']} fields from {pdf_file.name}", "SUCCESS")
                total_fields += pdf_data['total_fields']
                success_count += 1
            
            if success_count > 0:
                self.log(f"Stage 2 completed: {success_count} PDFs processed, {total_fields} total fields", "SUCCESS")
                return True
            else:
                self.log("Stage 2 failed: No PDFs were processed", "ERROR")
                return False
            
        except Exception as e:
            self.log(f"Stage 2 failed: {e}", "ERROR")
            self.stats['errors'].append(f"Extract stage: {e}")
            return False
    
    def stage_match_labels(self, pdf_files: List[Path]) -> bool:
        """Stage 3: Match labels using AI agent"""
        self.log("Stage 3: Matching labels with AI agent...", "PROGRESS")
        
        try:
            # Initialize agent
            agent = LabelMatchingAgent(LABEL_LIST_PATH)
            
            success_count = 0
            
            # Process each PDF's field JSON file
            for pdf_file in pdf_files:
                json_file = EXTRACT_OUTPUT_DIR / f"{pdf_file.stem}_fields.json"
                if not json_file.exists():
                    self.log(f"Field JSON not found: {json_file}", "ERROR")
                    continue
                
                self.log(f"Processing {json_file.name}...", "INFO")
                try:
                    results = agent.process_pdf_fields(json_file)
                    if results:
                        self.log(f"Successfully processed {json_file.name}", "SUCCESS")
                        success_count += 1
                    else:
                        self.log(f"Failed to process {json_file.name}", "ERROR")
                except Exception as e:
                    self.log(f"Error processing {json_file.name}: {e}", "ERROR")
            
            if success_count > 0:
                self.log(f"Stage 3 completed: {success_count} JSON files processed", "SUCCESS")
                return True
            else:
                self.log("Stage 3 failed: No JSON files were processed", "ERROR")
                return False
            
        except Exception as e:
            self.log(f"Stage 3 failed: {e}", "ERROR")
            self.stats['errors'].append(f"Match stage: {e}")
            return False
    
    def stage_apply_labels(self, pdf_files: List[Path]) -> bool:
        """Stage 4: Apply standardized labels"""
        self.log("Stage 4: Applying standardized labels...", "PROGRESS")
        
        try:
            success_count = 0
            
            # Process each PDF
            for pdf_file in pdf_files:
                # Check if standardized JSON exists
                json_name = f"{pdf_file.stem}_standardized.json"
                json_path = APPLY_STANDARDIZED_DIR / json_name
                
                if not json_path.exists():
                    self.log(f"No standardized JSON found for {pdf_file.name}", "WARNING")
                    continue
                
                # Check if unlocked PDF exists
                unlocked_pdf = APPLY_INPUT_DIR / pdf_file.name
                if not unlocked_pdf.exists():
                    self.log(f"Unlocked PDF not found: {unlocked_pdf}", "ERROR")
                    continue
                
                self.log(f"Applying labels to {pdf_file.name}...", "INFO")
                
                output_filename = f"{pdf_file.stem}_refined.pdf"
                output_path = APPLY_OUTPUT_DIR / output_filename
                
                # Find the corresponding fields JSON file
                fields_json_name = f"{pdf_file.stem}_fields.json"
                fields_json_path = EXTRACT_OUTPUT_DIR / fields_json_name
                
                if not fields_json_path.exists():
                    self.log(f"Fields JSON not found: {fields_json_path}", "ERROR")
                    self.stats['errors'].append(f"Apply stage: Fields JSON not found for {pdf_file.name}")
                    continue
                
                applicator = LabelApplicator(unlocked_pdf, json_path, fields_json_path)
                success = applicator.apply_labels(output_path)
                
                if success:
                    self.log(f"Successfully applied labels to {pdf_file.name}", "SUCCESS")
                    success_count += 1
                else:
                    self.log(f"Failed to apply labels to {pdf_file.name}", "ERROR")
            
            if success_count > 0:
                self.log(f"Stage 4 completed: {success_count} PDFs processed", "SUCCESS")
                return True
            else:
                self.log("Stage 4 failed: No PDFs were processed", "ERROR")
                return False
            
        except Exception as e:
            self.log(f"Stage 4 failed: {e}", "ERROR")
            self.stats['errors'].append(f"Apply stage: {e}")
            return False
    
    def process_single_pdf(self, pdf_file: Path) -> bool:
        """Process a single PDF through all stages"""
        pdf_name = pdf_file.name
        self.log(f"Processing {pdf_name}...", "PROGRESS")
        
        stage_start = time.time()
        
        try:
            # Stage 1: Unlock
            if not self.stage_unlock_pdfs([pdf_file]):
                return False
            
            # Stage 2: Extract
            if not self.stage_extract_fields([pdf_file]):
                return False
            
            # Stage 3: Match
            if not self.stage_match_labels([pdf_file]):
                return False
            
            # Stage 4: Apply
            if not self.stage_apply_labels([pdf_file]):
                return False
            
            processing_time = time.time() - stage_start
            self.stats['processing_times'][pdf_name] = processing_time
            self.stats['successful_pdfs'] += 1
            
            self.log(f"Successfully processed {pdf_name} in {processing_time:.1f}s", "SUCCESS")
            return True
            
        except Exception as e:
            self.log(f"Failed to process {pdf_name}: {e}", "ERROR")
            self.stats['failed_pdfs'] += 1
            self.stats['errors'].append(f"{pdf_name}: {e}")
            return False
    
    def run_pipeline(self, pdf_files: Optional[List[Path]] = None) -> bool:
        """Run the complete pipeline"""
        self.start_time = time.time()
        
        self.log("=" * 80, "INFO")
        self.log("[PIPELINE] TEMPODYN PRE-PROCESSOR PIPELINE", "INFO")
        self.log("=" * 80, "INFO")
        
        # Check prerequisites
        if not self.check_prerequisites():
            return False
        
        # Get PDFs to process
        if pdf_files is None:
            pdf_files = self.get_pdfs_to_process()
        
        if not pdf_files:
            self.log("No PDFs to process!", "WARNING")
            return True
        
        self.log(f"Found {len(pdf_files)} PDF(s) to process:", "INFO")
        for i, pdf_file in enumerate(pdf_files, 1):
            self.log(f"  {i}. {pdf_file.name}", "INFO")
        
        # Process each PDF
        all_successful = True
        for i, pdf_file in enumerate(pdf_files, 1):
            self.log(f"\n{'=' * 60}", "INFO")
            self.log(f"Processing PDF {i}/{len(pdf_files)}: {pdf_file.name}", "INFO")
            self.log(f"{'=' * 60}", "INFO")
            
            success = self.process_single_pdf(pdf_file)
            if not success:
                all_successful = False
        
        # Print final summary
        self.print_summary()
        
        # Clean up any temporary files
        self.cleanup_temp_files()
        
        return all_successful
    
    def print_summary(self):
        """Print processing summary"""
        total_time = time.time() - self.start_time if self.start_time else 0
        
        self.log("\n" + "=" * 80, "INFO")
        self.log("📊 PROCESSING SUMMARY", "INFO")
        self.log("=" * 80, "INFO")
        
        self.log(f"Total PDFs processed:     {self.stats['total_pdfs']}", "INFO")
        self.log(f"Successful:               {self.stats['successful_pdfs']}", "SUCCESS" if self.stats['successful_pdfs'] > 0 else "INFO")
        self.log(f"Failed:                   {self.stats['failed_pdfs']}", "ERROR" if self.stats['failed_pdfs'] > 0 else "INFO")
        self.log(f"Skipped (already done):   {self.stats['skipped_pdfs']}", "WARNING" if self.stats['skipped_pdfs'] > 0 else "INFO")
        self.log(f"Total processing time:    {total_time:.1f}s", "INFO")
        
        if self.stats['processing_times']:
            avg_time = sum(self.stats['processing_times'].values()) / len(self.stats['processing_times'])
            self.log(f"Average time per PDF:     {avg_time:.1f}s", "INFO")
        
        if self.stats['errors']:
            self.log(f"\n[ERROR] Errors encountered:", "ERROR")
            for error in self.stats['errors']:
                self.log(f"  • {error}", "ERROR")
        
        if self.stats['successful_pdfs'] > 0:
            self.log(f"\n[SUCCESS] Refined PDFs saved to: {APPLY_OUTPUT_DIR.absolute()}", "SUCCESS")
            self.log("[SUCCESS] Pipeline completed successfully!", "SUCCESS")


def main():
    """Main command-line interface"""
    parser = argparse.ArgumentParser(
        description="TempoDyn Pre-Processor - Complete PDF Processing Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python app.py                    # Process all PDFs in 0_locked_pdfs/
  python app.py --pdf ssa-3.pdf   # Process specific PDF
  python app.py --quiet           # Run with minimal output
  python app.py --check           # Check prerequisites only
        """
    )
    
    parser.add_argument(
        '--pdf', 
        type=str, 
        help='Process specific PDF file (must be in 0_locked_pdfs/)'
    )
    
    parser.add_argument(
        '--quiet', 
        action='store_true', 
        help='Run with minimal output'
    )
    
    parser.add_argument(
        '--check', 
        action='store_true', 
        help='Check prerequisites only (do not process)'
    )
    
    args = parser.parse_args()
    
    # Initialize orchestrator
    orchestrator = PipelineOrchestrator(verbose=not args.quiet)
    
    # Check prerequisites
    if not orchestrator.check_prerequisites():
        sys.exit(1)
    
    if args.check:
        orchestrator.log("Prerequisites check completed successfully!", "SUCCESS")
        sys.exit(0)
    
    # Determine PDFs to process
    pdf_files = None
    if args.pdf:
        pdf_path = UNLOCK_INPUT_DIR / args.pdf
        if not pdf_path.exists():
            orchestrator.log(f"PDF not found: {pdf_path}", "ERROR")
            sys.exit(1)
        pdf_files = [pdf_path]
    
    # Run pipeline
    success = orchestrator.run_pipeline(pdf_files)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
