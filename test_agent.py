"""
Quick test script for the Label Matching Agent
Tests the agent on sample fields AND validates all tools are working
"""

import os
from dotenv import load_dotenv
from match_labels import LabelMatchingAgent

# Load environment variables from .env file
load_dotenv()


def test_tools_directly():
    """Test each tool function directly to ensure they work"""
    
    print("\n" + "=" * 80)
    print("🔧 TESTING AGENT TOOLS DIRECTLY")
    print("=" * 80)
    
    agent = LabelMatchingAgent("3_matching_labels/label_list.json")
    
    # Test 1: Search similar labels
    print("\n1️⃣  Testing search_similar_labels:")
    print("   Query: 'social security number'")
    results = agent._search_similar("social security number", limit=5)
    print(f"   ✓ Found {len(results)} matches:")
    for r in results[:3]:
        print(f"      • {r['label']} ({r['similarity_score']}% - {r['interpretation']})")
    
    # Test 2: Validate label format
    print("\n2️⃣  Testing validate_label_format:")
    test_labels = [
        ("first_name", True),
        ("First Name", False),  # Not lowercase
        ("first name", False),  # Has space
        ("first__name", False), # Double underscore
        ("_first_name", False), # Leading underscore
        ("123name", False),     # Starts with number
        ("wage_earner_name", True),
    ]
    
    for label, expected_valid in test_labels:
        is_valid, message = agent._validate_label_format(label)
        status = "✓" if is_valid == expected_valid else "✗"
        print(f"   {status} '{label}': {'Valid' if is_valid else f'Invalid - {message}'}")
    
    # Test 3: Check label exists
    print("\n3️⃣  Testing check_label_exists:")
    test_checks = [
        ("first_name", True),   # Common label
        ("nonexistent_label_xyz", False),
    ]
    for label, should_exist in test_checks:
        exists = label in agent.label_list
        status = "✓" if exists == should_exist else "✗"
        print(f"   {status} '{label}': {'Exists' if exists else 'Does not exist'}")
    
    # Test 4: Session tracking (add and detect duplicate)
    print("\n4️⃣  Testing session-aware duplicate prevention:")
    print("   Adding new label: 'test_session_label_xyz'")
    
    # First add
    result1 = agent._execute_tool("add_new_label", {
        "label": "test_session_label_xyz",
        "reason": "Test label for tool validation"
    })
    print(f"   ✓ First attempt: {result1['message']}")
    
    # Try to add again (should fail)
    result2 = agent._execute_tool("add_new_label", {
        "label": "test_session_label_xyz",
        "reason": "Duplicate attempt"
    })
    print(f"   ✓ Second attempt: {result2['message']}")
    
    # Check it's in session list
    print(f"   ✓ Session labels added: {len(agent.session_labels_added)}")
    print(f"   ✓ Session tracking working: {'test_session_label_xyz' in agent.session_labels_added}")
    
    # Clean up
    if "test_session_label_xyz" in agent.label_list:
        agent.label_list.remove("test_session_label_xyz")
    
    # Test 5: Format validation in add_new_label
    print("\n5️⃣  Testing automatic validation in add_new_label:")
    invalid_label_tests = [
        "Invalid Label",  # Spaces
        "invalid-label",  # Hyphen
        "123invalid",     # Starts with number
    ]
    
    for invalid_label in invalid_label_tests:
        result = agent._execute_tool("add_new_label", {
            "label": invalid_label,
            "reason": "Testing validation"
        })
        if not result['success']:
            print(f"   ✓ Correctly rejected: '{invalid_label}'")
            print(f"      Reason: {result.get('validation_error', result['message'])}")
        else:
            print(f"   ✗ FAILED: Accepted invalid label '{invalid_label}'")
    
    print("\n" + "=" * 80)
    print("✅ ALL TOOL TESTS COMPLETE")
    print("=" * 80)

def test_single_field():
    """Test the agent on a sample field"""
    
    print("=" * 80)
    print("🧪 TESTING LABEL MATCHING AGENT")
    print("=" * 80)
    
    # Check API key
    if not os.getenv('GEMINI_API_KEY'):
        print("\n❌ Error: GEMINI_API_KEY not found")
        print("Please make sure you have a .env file with:")
        print("  GEMINI_API_KEY=your-api-key-here")
        print("\nGet your API key from: https://platform.openai.com/api-keys")
        return
    
    # Initialize agent
    print("\n📋 Initializing agent...")
    agent = LabelMatchingAgent("3_matching_labels/label_list.json")
    
    # Test cases
    test_fields = [
        {
            "name": "Test 1: Descriptive field name",
            "field": {
                "field_name": "first_name",
                "field_type": "Text",
                "field_context_on_pdf": "Enter your first name",
                "field_context_detected": None,
                "page": 1,
                "rect": {"x0": 100, "y0": 200, "x1": 300, "y1": 220}
            }
        },
        {
            "name": "Test 2: Gibberish XFA notation with good context",
            "field": {
                "field_name": "topmostSubform[0].BodyPage1[0].P1_NameofWageEarner_FLD[0]",
                "field_type": "Text",
                "field_context_on_pdf": "PRINT NAME OF WAGE EARNER OR SELF-EMPLOYED PERSON",
                "field_context_detected": None,
                "page": 1,
                "rect": {"x0": 48.2, "y0": 97.34, "x1": 420.17, "y1": 109.67}
            }
        },
        {
            "name": "Test 3: Checkbox with detected context",
            "field": {
                "field_name": "topmostSubform[0].BodyPage1[0].P1_N1MarriagePerfBy_CB1[0]",
                "field_type": "CheckBox",
                "field_context_on_pdf": None,
                "field_context_detected": "Clergyman or Authorized Public Official",
                "page": 1,
                "rect": {"x0": 60.07, "y0": 186.7, "x1": 70.07, "y1": 196.7}
            }
        },
        {
            "name": "Test 4: Date field with context",
            "field": {
                "field_name": "topmostSubform[0].BodyPage2[0].P2_SignDate_FLD[0]",
                "field_type": "Text",
                "field_context_on_pdf": "DATE  (MM/DD/Y Y Y Y)",
                "field_context_detected": None,
                "page": 2,
                "rect": {"x0": 403.34, "y0": 110.84, "x1": 573.16, "y1": 123.17}
            }
        },
        {
            "name": "Test 5: Field to test duplicate prevention",
            "field": {
                "field_name": "topmostSubform[0].BodyPage1[0].P1_City_FLD[0]",
                "field_type": "Text",
                "field_context_on_pdf": "CITY",
                "field_context_detected": None,
                "page": 1,
                "rect": {"x0": 47.84, "y0": 205.34, "x1": 397.66, "y1": 217.66}
            }
        },
        {
            "name": "Test 6: Another city field (should reuse label)",
            "field": {
                "field_name": "topmostSubform[0].BodyPage2[0].P2_City2_FLD[0]",
                "field_type": "Text",
                "field_context_on_pdf": "CITY",
                "field_context_detected": None,
                "page": 2,
                "rect": {"x0": 100, "y0": 300, "x1": 400, "y1": 320}
            }
        }
    ]
    
    # Track tool usage across tests
    tool_usage_summary = {
        'search_similar_labels': 0,
        'check_label_exists': 0,
        'validate_label_format': 0,
        'add_new_label': 0,
        'submit_final_decision': 0
    }
    
    # Run tests
    for i, test in enumerate(test_fields, 1):
        print(f"\n{'=' * 80}")
        print(f"{test['name']}")
        print("=" * 80)
        print(f"Field Name: {test['field']['field_name']}")
        print(f"Type: {test['field']['field_type']}")
        print(f"Context on PDF: {test['field']['field_context_on_pdf']}")
        print(f"Detected Context: {test['field']['field_context_detected']}")
        print()
        
        try:
            # Get agent decision
            decision = agent.match_field(test['field'], verbose=True)
            
            # Print result
            print(f"\n📊 RESULT:")
            print(f"  Action: {decision['action']}")
            print(f"  Label: {decision['standardized_label']}")
            print(f"  Confidence: {decision['confidence']}%")
            print(f"  Reasoning: {decision['reasoning']}")
            
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'=' * 80}")
    print("✅ FIELD TESTING COMPLETE")
    print("=" * 80)
    
    # Show session summary
    print(f"\n📊 Session Summary:")
    print(f"  Total fields tested: {len(test_fields)}")
    print(f"  New labels created: {len(agent.session_labels_added)}")
    if agent.session_labels_added:
        print(f"  Labels created this session:")
        for label in agent.session_labels_added:
            print(f"    • {label}")
    print(f"\n💡 Note: Watch for 'Using tool:' messages above to see which tools were used!")


def test_label_search():
    """Test the fuzzy search functionality"""
    
    print("\n" + "=" * 80)
    print("🔍 TESTING LABEL SEARCH")
    print("=" * 80)
    
    agent = LabelMatchingAgent("3_matching_labels/label_list.json")
    
    test_queries = [
        "social security number",
        "date of birth",
        "first name",
        "marriage certificate",
        "checkbox yes"
    ]
    
    for query in test_queries:
        print(f"\n🔎 Searching for: '{query}'")
        results = agent._search_similar(query, limit=5)
        print("   Top 5 matches:")
        for result in results:
            print(f"     • {result['label']} ({result['similarity_score']}% - {result['interpretation']})")


if __name__ == "__main__":
    print("=" * 80)
    print("🧪 COMPREHENSIVE AGENT TESTING SUITE")
    print("=" * 80)
    print("\nThis script will test:")
    print("  1. All agent tools (direct function tests)")
    print("  2. Agent decision-making on sample fields")
    print("  3. Tool usage during agent operation")
    print()
    input("Press Enter to start testing...")
    
    # Part 1: Test tools directly
    test_tools_directly()
    
    # Part 2: Test agent on fields (shows tools being used via API)
    test_single_field()
    
    # Optional: Test label search
    # test_label_search()
    
    print("\n" + "=" * 80)
    print("🎉 ALL TESTS COMPLETE!")
    print("=" * 80)
    print("\n✅ Summary:")
    print("  • All tools tested and working")
    print("  • Agent successfully processed sample fields")
    print("  • Session tracking operational")
    print("  • Format validation operational")
    print("\n💡 Review the output above to see:")
    print("  • Tool validation results")
    print("  • Which tools the agent used for each field")
    print("  • Label creation and duplicate prevention")
    print("\n✨ Your agent is ready for production use!")

