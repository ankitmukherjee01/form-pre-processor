# TempoDyn Pre-Processor - Complete Pipeline

## 🚀 Quick Start

The `app.py` file provides a complete command-line interface to process PDFs through the entire pipeline:

### **Basic Usage**

```bash
# Process all PDFs in the 0_locked_pdfs/ folder
python app.py

# Process a specific PDF
python app.py --pdf ssa-3.pdf

# Run with minimal output
python app.py --quiet

# Check prerequisites only
python app.py --check
```

### **What It Does**

The app automatically runs all 4 stages of the pipeline:

1. **🔓 Unlock PDFs** - Removes restrictions from locked PDFs
2. **📋 Extract Fields** - Extracts field metadata and context
3. **🤖 Match Labels** - Uses AI to standardize field names
4. **🏷️ Apply Labels** - Creates refined PDFs with clean field names

### **Prerequisites**

Make sure you have:
- ✅ OpenAI API key set in environment: `OPENAI_API_KEY=your-key`
- ✅ All required Python packages installed
- ✅ PDFs to process in `0_locked_pdfs/` folder

### **Output**

Processed PDFs will be saved to `5_refined_pdfs/` with standardized field names.

### **Example Output**

```
[14:30:15] ℹ️  🚀 TEMPODYN PRE-PROCESSOR PIPELINE
[14:30:15] ℹ️  ================================================================================
[14:30:15] 🔄 Checking prerequisites...
[14:30:15] ✅ All prerequisites met!
[14:30:15] ℹ️  Found 1 PDF(s) to process:
[14:30:15] ℹ️    1. ssa-3.pdf
[14:30:15] ℹ️  
[14:30:15] ℹ️  ============================================================
[14:30:15] ℹ️  Processing PDF 1/1: ssa-3.pdf
[14:30:15] ℹ️  ============================================================
[14:30:15] 🔄 Processing ssa-3.pdf...
[14:30:15] 🔄 Stage 1: Unlocking 1 PDF(s)...
[14:30:15] ✅ Stage 1 completed successfully!
[14:30:15] 🔄 Stage 2: Extracting field information...
[14:30:15] ✅ Stage 2 completed successfully!
[14:30:15] 🔄 Stage 3: Matching labels with AI agent...
[14:30:15] ✅ Stage 3 completed successfully!
[14:30:15] 🔄 Stage 4: Applying standardized labels...
[14:30:15] ✅ Stage 4 completed successfully!
[14:30:15] ✅ Successfully processed ssa-3.pdf in 45.2s
[14:30:15] ℹ️  
[14:30:15] ℹ️  ================================================================================
[14:30:15] ℹ️  📊 PROCESSING SUMMARY
[14:30:15] ℹ️  ================================================================================
[14:30:15] ℹ️  Total PDFs processed:     1
[14:30:15] ✅ Successful:               1
[14:30:15] ℹ️  Failed:                   0
[14:30:15] ℹ️  Skipped (already done):   0
[14:30:15] ℹ️  Total processing time:    45.2s
[14:30:15] ℹ️  Average time per PDF:     45.2s
[14:30:15] ✅ ✨ Refined PDFs saved to: C:\Users\ankit\Documents\Main Vault\1 Projects\TempoDyn\Pre-Processor\5_refined_pdfs
[14:30:15] ✅ 🎉 Pipeline completed successfully!
```

### **Command Line Options**

| Option | Description |
|--------|-------------|
| `--pdf FILE` | Process specific PDF file only |
| `--quiet` | Run with minimal output |
| `--check` | Check prerequisites only (don't process) |
| `--help` | Show help message |

### **Error Handling**

The app handles errors gracefully:
- ❌ Missing API key → Clear instructions to set it
- ❌ Missing directories → Creates them automatically  
- ❌ Processing failures → Continues with other PDFs
- ❌ Individual PDF errors → Logs error and continues

### **Performance**

- **Typical processing time**: 30-60 seconds per PDF
- **Memory usage**: Moderate (depends on PDF complexity)
- **Concurrent processing**: Single-threaded (processes one PDF at a time)

---

**Ready to process your PDFs?** Just run `python app.py` and let the AI do the work! 🚀
