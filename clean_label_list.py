"""
Clean and standardize the existing label list
- Convert to lowercase snake_case
- Remove duplicates
- Sort alphabetically
- Flag problematic labels
"""

import json
import re
from pathlib import Path

LABEL_LIST_PATH = Path("3_matching_labels/label_list.json")
BACKUP_PATH = Path("3_matching_labels/label_list_backup.json")


def to_snake_case(text):
    """Convert text to snake_case"""
    # Replace special characters with spaces
    text = re.sub(r'[^\w\s]', ' ', text)
    # Replace multiple spaces with single space
    text = re.sub(r'\s+', ' ', text)
    # Convert to lowercase
    text = text.lower().strip()
    # Replace spaces with underscores
    text = text.replace(' ', '_')
    # Remove multiple underscores
    text = re.sub(r'_+', '_', text)
    # Remove leading/trailing underscores
    text = text.strip('_')
    return text


def clean_label(label):
    """Clean and standardize a single label"""
    # If already lowercase with underscores, keep it
    if label == label.lower() and ' ' not in label and re.match(r'^[a-z][a-z0-9_]*$', label):
        return label, True, "Already clean"
    
    # Convert to snake_case
    cleaned = to_snake_case(label)
    
    # Validate
    if not cleaned:
        return label, False, "Empty after cleaning"
    
    if not re.match(r'^[a-z][a-z0-9_]*$', cleaned):
        return label, False, f"Invalid characters after cleaning: {cleaned}"
    
    return cleaned, True, "Converted to snake_case"


def main():
    """Clean the label list"""
    
    print("=" * 80)
    print("🧹 CLEANING LABEL LIST")
    print("=" * 80)
    
    # Load existing labels
    print(f"\n📋 Loading labels from: {LABEL_LIST_PATH}")
    with open(LABEL_LIST_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    original_labels = data.get('standardized_field_labels', [])
    print(f"   Found {len(original_labels)} labels")
    
    # Backup original
    print(f"\n💾 Creating backup: {BACKUP_PATH}")
    with open(BACKUP_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    # Clean labels
    print(f"\n🔧 Cleaning labels...")
    cleaned_labels = []
    problematic = []
    conversions = []
    
    for i, label in enumerate(original_labels, 1):
        cleaned, success, reason = clean_label(label)
        
        if success:
            cleaned_labels.append(cleaned)
            if cleaned != label:
                conversions.append({
                    'original': label,
                    'cleaned': cleaned,
                    'reason': reason
                })
        else:
            problematic.append({
                'original': label,
                'attempted': cleaned,
                'reason': reason
            })
    
    # Remove duplicates and sort
    original_count = len(cleaned_labels)
    cleaned_labels = sorted(set(cleaned_labels))
    duplicates_removed = original_count - len(cleaned_labels)
    
    # Update data
    data['standardized_field_labels'] = cleaned_labels
    if 'metadata' in data:
        data['metadata']['total_labels'] = len(cleaned_labels)
        data['metadata']['last_cleaned'] = '2025-10-14'
    
    # Save cleaned version
    print(f"\n💾 Saving cleaned labels: {LABEL_LIST_PATH}")
    with open(LABEL_LIST_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    # Print summary
    print("\n" + "=" * 80)
    print("📊 CLEANING SUMMARY")
    print("=" * 80)
    print(f"Original labels:        {len(original_labels)}")
    print(f"Cleaned labels:         {len(cleaned_labels)}")
    print(f"Conversions:            {len(conversions)}")
    print(f"Duplicates removed:     {duplicates_removed}")
    print(f"Problematic labels:     {len(problematic)}")
    
    if conversions:
        print(f"\n✏️  Converted {len(conversions)} labels to snake_case:")
        for conv in conversions[:10]:  # Show first 10
            print(f"   • '{conv['original']}' → '{conv['cleaned']}'")
        if len(conversions) > 10:
            print(f"   ... and {len(conversions) - 10} more")
    
    if problematic:
        print(f"\n⚠️  {len(problematic)} problematic labels (not added):")
        for prob in problematic[:10]:  # Show first 10
            print(f"   • '{prob['original']}' - {prob['reason']}")
        if len(problematic) > 10:
            print(f"   ... and {len(problematic) - 10} more")
    
    # Save problematic labels report
    if problematic:
        report_path = Path("3_matching_labels/problematic_labels.json")
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump({
                'problematic_labels': problematic,
                'total_count': len(problematic)
            }, f, indent=2, ensure_ascii=False)
        print(f"\n📄 Problematic labels saved to: {report_path}")
    
    print("\n✅ Label list cleaned successfully!")
    print(f"💾 Backup saved to: {BACKUP_PATH}")
    print(f"📋 New count: {len(cleaned_labels)} labels")


if __name__ == "__main__":
    main()

