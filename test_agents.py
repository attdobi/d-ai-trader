#!/usr/bin/env python3
"""
Test script for individual agents
Run this to test each agent component separately
"""

from agent_executor import run_summarizer_agents, run_decider_agent, run_feedback_agent, run_all_agents

def test_summarizer():
    """Test summarizer agent"""
    print("📰 Testing Summarizer Agent...")
    result = run_summarizer_agents()
    print(f"   Result: {'✅' if result.success else '❌'} {result.message}")
    return result.success

def test_decider():
    """Test decider agent"""
    print("🤖 Testing Decider Agent...")
    result = run_decider_agent()
    print(f"   Result: {'✅' if result.success else '❌'} {result.message}")
    return result.success

def test_feedback():
    """Test feedback agent"""
    print("📊 Testing Feedback Agent...")
    result = run_feedback_agent()
    print(f"   Result: {'✅' if result.success else '❌'} {result.message}")
    return result.success

def test_all():
    """Test all agents"""
    print("🚀 Testing All Agents...")
    results = run_all_agents()
    success_count = sum(1 for r in results if r.success)
    total_count = len(results)
    print(f"   Result: {success_count}/{total_count} agents successful")

    for result in results:
        status = "✅" if result.success else "❌"
        print(f"   {status} {result.agent_type}: {result.message}")

    return success_count == total_count

def main():
    """Main test function"""
    print("🧪 D-AI-Trader Agent Testing Suite")
    print("=" * 40)

    tests = [
        ("Summarizer", test_summarizer),
        ("Decider", test_decider),
        ("Feedback", test_feedback),
        ("All Agents", test_all)
    ]

    results = []
    for name, test_func in tests:
        print(f"\n🔬 Running {name} Test...")
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            print(f"   ❌ Test failed with exception: {e}")
            results.append((name, False))

    print("\n" + "=" * 40)
    print("📊 Test Results Summary:")
    for name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"   {name}: {status}")

    total_passed = sum(1 for _, success in results if success)
    print(f"\n🎯 Overall: {total_passed}/{len(results)} tests passed")

    if total_passed == len(results):
        print("🎉 All tests passed! Your system is ready.")
    else:
        print("⚠️  Some tests failed. Check the output above for details.")

if __name__ == "__main__":
    main()
