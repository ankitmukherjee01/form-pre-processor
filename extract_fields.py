"""
PDF Form Fields Extractor
Extracts all fillable field information from unlocked PDFs and saves to JSON.
"""

import os
import json
from pathlib import Path
import fitz  # PyMuPDF

# Define input and output directories
INPUT_DIR = Path("1_unlocked_pdfs")
OUTPUT_DIR = Path("2_fields_json")

# Create output directory if it doesn't exist
OUTPUT_DIR.mkdir(exist_ok=True)

# Field type mapping
FIELD_TYPE_MAP = {
    fitz.PDF_WIDGET_TYPE_BUTTON: "Button",
    fitz.PDF_WIDGET_TYPE_CHECKBOX: "CheckBox",
    fitz.PDF_WIDGET_TYPE_COMBOBOX: "ComboBox",
    fitz.PDF_WIDGET_TYPE_LISTBOX: "ListBox",
    fitz.PDF_WIDGET_TYPE_RADIOBUTTON: "RadioButton",
    fitz.PDF_WIDGET_TYPE_SIGNATURE: "Signature",
    fitz.PDF_WIDGET_TYPE_TEXT: "Text",
    fitz.PDF_WIDGET_TYPE_UNKNOWN: "Unknown"
}

def extract_nearby_text(page, widget, direction="left", search_distance=200):
    """
    Extract text near a field widget in a specific direction.
    
    Args:
        page: PyMuPDF page object
        widget: Widget object
        direction: "left", "right", "top", or "bottom"
        search_distance: How many points to search in the specified direction
    
    Returns:
        str: Nearby text, cleaned up
    """
    field_rect = widget.rect
    
    # Define search rectangle based on direction
    if direction == "left":
        # Search to the left of the field
        search_rect = fitz.Rect(
            max(0, field_rect.x0 - search_distance),
            field_rect.y0 - 5,  # Small vertical margin
            field_rect.x0,
            field_rect.y1 + 5
        )
    elif direction == "right":
        # Search to the right of the field
        search_rect = fitz.Rect(
            field_rect.x1,
            field_rect.y0 - 5,
            min(page.rect.width, field_rect.x1 + search_distance),
            field_rect.y1 + 5
        )
    elif direction == "top":
        # Search above the field
        search_rect = fitz.Rect(
            field_rect.x0 - 5,
            max(0, field_rect.y1),
            field_rect.x1 + 5,
            min(page.rect.height, field_rect.y1 + search_distance)
        )
    elif direction == "bottom":
        # Search below the field
        search_rect = fitz.Rect(
            field_rect.x0 - 5,
            max(0, field_rect.y0 - search_distance),
            field_rect.x1 + 5,
            field_rect.y0
        )
    else:
        return ""
    
    # Extract text from the search area
    try:
        text = page.get_text("text", clip=search_rect)
        # Clean up: remove extra whitespace, newlines
        text = " ".join(text.split())
        return text.strip()
    except:
        return ""

def find_best_label(page, widget):
    """
    Find the best label for a field by searching in all directions and choosing the closest.
    
    Args:
        page: PyMuPDF page object
        widget: Widget object
    
    Returns:
        str: Best label found
    """
    field_type = widget.field_type
    field_rect = widget.rect
    
    # Search in all directions and collect results with distances
    direction_results = []
    
    directions = ["left", "right", "top", "bottom"]
    search_distances = {
        "left": 200,
        "right": 200, 
        "top": 150,
        "bottom": 150
    }
    
    for direction in directions:
        text = extract_nearby_text(page, widget, direction, search_distances[direction])
        if text and len(text.strip()) > 0:
            # Calculate approximate distance (simplified)
            if direction in ["left", "right"]:
                distance = abs(field_rect.x0 - (field_rect.x0 - search_distances[direction] if direction == "left" else field_rect.x1 + search_distances[direction]))
            else:
                distance = abs(field_rect.y0 - (field_rect.y1 + search_distances[direction] if direction == "top" else field_rect.y0 - search_distances[direction]))
            
            direction_results.append({
                'text': text.strip(),
                'direction': direction,
                'distance': distance
            })
    
    if not direction_results:
        return ""
    
    # For checkboxes and radio buttons, prioritize text to the RIGHT
    if field_type in [fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON]:
        # Look for right direction first
        right_results = [r for r in direction_results if r['direction'] == 'right']
        if right_results:
            return right_results[0]['text']
        
        # Then try left
        left_results = [r for r in direction_results if r['direction'] == 'left']
        if left_results:
            return left_results[0]['text']
    
    # For text fields, prioritize LEFT then TOP, but choose closest
    else:
        # Prioritize left direction
        left_results = [r for r in direction_results if r['direction'] == 'left']
        if left_results:
            # Return the closest left result
            closest_left = min(left_results, key=lambda x: x['distance'])
            return closest_left['text']
        
        # Then try top
        top_results = [r for r in direction_results if r['direction'] == 'top']
        if top_results:
            closest_top = min(top_results, key=lambda x: x['distance'])
            return closest_top['text']
    
    # Fallback: return the closest result overall
    if direction_results:
        closest = min(direction_results, key=lambda x: x['distance'])
        return closest['text']
    
    return ""

def extract_field_info(widget, page):
    """
    Extract detailed information from a form field widget.
    
    Args:
        widget: PyMuPDF widget object
        page: PyMuPDF page object (for nearby text extraction)
    
    Returns:
        dict: Field information
    """
    # Get built-in label (from /TU entry)
    builtin_label = widget.field_label if hasattr(widget, 'field_label') else None
    
    # Only extract context from PDF text if built-in context is missing
    context_all_directions = {}
    nearby_label = None
    
    if not builtin_label or builtin_label.strip() == "":
        # Extract context from all directions only when needed
        directions = ["left", "right", "top", "bottom"]
        
        for direction in directions:
            text = extract_nearby_text(page, widget, direction, search_distance=200)
            if text and len(text.strip()) > 0:
                context_all_directions[direction] = text.strip()
        
        # Get the best single label (for backward compatibility)
        nearby_label = find_best_label(page, widget)
    
    field_info = {
        'field_name': widget.field_name,
        'field_context_on_pdf': builtin_label,
        'field_context_detected': nearby_label if nearby_label else None,
        'field_context_all_directions': context_all_directions,  # NEW: All directions
        'field_type': FIELD_TYPE_MAP.get(widget.field_type, "Unknown"),
        'field_type_code': widget.field_type,
        'field_value': widget.field_value,
        'field_flags': widget.field_flags,
        'rect': {
            'x0': round(widget.rect.x0, 2),
            'y0': round(widget.rect.y0, 2),
            'x1': round(widget.rect.x1, 2),
            'y1': round(widget.rect.y1, 2),
            'width': round(widget.rect.width, 2),
            'height': round(widget.rect.height, 2)
        }
    }
    
    # Add type-specific properties
    if widget.field_type == fitz.PDF_WIDGET_TYPE_TEXT:
        field_info['text_format'] = widget.text_format if hasattr(widget, 'text_format') else None
        field_info['text_maxlen'] = widget.text_maxlen if hasattr(widget, 'text_maxlen') else None
    
    elif widget.field_type in [fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX]:
        field_info['choice_values'] = widget.choice_values if hasattr(widget, 'choice_values') else None
    
    elif widget.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
        field_info['is_checked'] = widget.field_value if widget.field_value else False
    
    # Check if field is read-only
    field_info['is_readonly'] = bool(widget.field_flags & (1 << 0)) if widget.field_flags else False
    field_info['is_required'] = bool(widget.field_flags & (1 << 1)) if widget.field_flags else False
    field_info['is_no_export'] = bool(widget.field_flags & (1 << 2)) if widget.field_flags else False
    
    # Get button state (for radio buttons and checkboxes)
    if hasattr(widget, 'button_states'):
        field_info['button_states'] = widget.button_states()
    
    return field_info

def extract_fields_from_pdf(pdf_path):
    """
    Extract all form fields from a PDF.
    
    Args:
        pdf_path: Path to the PDF file
    
    Returns:
        dict: PDF information and fields
    """
    pdf_info = {
        'filename': pdf_path.name,
        'filepath': str(pdf_path),
        'total_pages': 0,
        'total_fields': 0,
        'pages': []
    }
    
    try:
        doc = fitz.open(pdf_path)
        pdf_info['total_pages'] = len(doc)
        
        # Iterate through all pages
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_info = {
                'page_number': page_num + 1,
                'fields': []
            }
            
            # Get all widgets (form fields) on this page
            widgets = page.widgets()
            
            if widgets:
                for widget in widgets:
                    field_info = extract_field_info(widget, page)  # Pass page for nearby text extraction
                    field_info['page'] = page_num + 1
                    page_info['fields'].append(field_info)
                    pdf_info['total_fields'] += 1
            
            # Only add page if it has fields
            if page_info['fields']:
                pdf_info['pages'].append(page_info)
        
        doc.close()
        
    except Exception as e:
        pdf_info['error'] = str(e)
    
    return pdf_info

def main():
    """Main function to extract fields from all PDFs."""
    
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
    
    total_fields = 0
    success_count = 0
    
    # Process each PDF file
    for pdf_file in pdf_files:
        print(f"Processing: {pdf_file.name}")
        
        pdf_data = extract_fields_from_pdf(pdf_file)
        
        if 'error' in pdf_data:
            print(f"  ❌ Error: {pdf_data['error']}")
        else:
            print(f"  ✓ Extracted {pdf_data['total_fields']} fields from {pdf_data['total_pages']} pages")
            total_fields += pdf_data['total_fields']
            success_count += 1
        
        # Save JSON file for this PDF
        output_file = OUTPUT_DIR / f"{pdf_file.stem}_fields.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(pdf_data, f, indent=2, ensure_ascii=False)
        
        print(f"  💾 Saved to: {output_file.name}\n")
    
    # Print summary
    print("=" * 60)
    print(f"Field extraction complete!")
    print(f"  Total PDFs processed: {success_count}/{len(pdf_files)}")
    print(f"  Total fields extracted: {total_fields}")
    print(f"\nJSON files saved to: {OUTPUT_DIR.absolute()}")

if __name__ == "__main__":
    main()

