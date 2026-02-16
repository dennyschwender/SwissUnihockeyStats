#!/usr/bin/env python3
"""
Script to verify the project is ready for GitHub.
Checks for common issues before publishing.
"""

import os
import sys
from pathlib import Path


class Colors:
    """ANSI color codes."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def check_file_exists(filepath, required=True):
    """Check if a file exists."""
    exists = Path(filepath).exists()
    status = f"{Colors.GREEN}✓{Colors.RESET}" if exists else f"{Colors.RED}✗{Colors.RESET}"
    req_text = "(required)" if required else "(optional)"
    print(f"  {status} {filepath} {req_text}")
    return exists


def check_placeholder_text(filepath, placeholders):
    """Check if file contains placeholder text that needs updating."""
    if not Path(filepath).exists():
        return True
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    found_placeholders = []
    for placeholder in placeholders:
        if placeholder in content:
            found_placeholders.append(placeholder)
    
    if found_placeholders:
        print(f"  {Colors.YELLOW}⚠{Colors.RESET} {filepath} contains placeholders:")
        for p in found_placeholders:
            print(f"      - {p}")
        return False
    return True


def main():
    """Run all checks."""
    print(f"\n{Colors.BOLD}SwissUnihockey GitHub Readiness Check{Colors.RESET}")
    print("=" * 60)
    
    all_passed = True
    
    # Check essential files
    print(f"\n{Colors.BOLD}📄 Essential Files:{Colors.RESET}")
    essential_files = [
        "README.md",
        "LICENSE",
        ".gitignore",
        "requirements.txt",
        "config.ini",
        "api/__init__.py",
        "api/client.py",
        "api/endpoints.py",
    ]
    
    for file in essential_files:
        if not check_file_exists(file, required=True):
            all_passed = False
    
    # Check documentation
    print(f"\n{Colors.BOLD}📚 Documentation:{Colors.RESET}")
    doc_files = [
        "GETTING_STARTED.md",
        "FEATURE_IDEAS.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        "SECURITY.md",
        "GITHUB_SETUP.md",
    ]
    
    for file in doc_files:
        check_file_exists(file, required=False)
    
    # Check GitHub configuration
    print(f"\n{Colors.BOLD}⚙️ GitHub Configuration:{Colors.RESET}")
    github_files = [
        ".github/workflows/tests.yml",
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/feature_request.md",
        ".github/pull_request_template.md",
    ]
    
    for file in github_files:
        check_file_exists(file, required=False)
    
    # Check for placeholders
    print(f"\n{Colors.BOLD}🔍 Checking for Placeholders:{Colors.RESET}")
    placeholders = ["YOUR_USERNAME", "your.email@example.com", "Your Name"]
    
    placeholder_files = [
        "README.md",
        "pyproject.toml",
    ]
    
    for file in placeholder_files:
        if not check_placeholder_text(file, placeholders):
            all_passed = False
    
    # Check for sensitive data
    print(f"\n{Colors.BOLD}🔒 Security Checks:{Colors.RESET}")
    sensitive_files = [
        "credentials.ini",
        ".env",
    ]
    
    has_sensitive = False
    for file in sensitive_files:
        if Path(file).exists():
            print(f"  {Colors.RED}⚠{Colors.RESET} {file} exists (should be in .gitignore)")
            has_sensitive = True
    
    if not has_sensitive:
        print(f"  {Colors.GREEN}✓{Colors.RESET} No sensitive files found")
    else:
        all_passed = False
    
    # Check .gitignore
    print(f"\n{Colors.BOLD}🚫 .gitignore Check:{Colors.RESET}")
    gitignore_entries = ['.venv/', '__pycache__/', '*.pyc', '.env', 'credentials.ini']
    
    if Path('.gitignore').exists():
        with open('.gitignore', 'r') as f:
            gitignore_content = f.read()
        
        missing = []
        for entry in gitignore_entries:
            if entry not in gitignore_content:
                missing.append(entry)
        
        if missing:
            print(f"  {Colors.YELLOW}⚠{Colors.RESET} Missing entries in .gitignore:")
            for entry in missing:
                print(f"      - {entry}")
        else:
            print(f"  {Colors.GREEN}✓{Colors.RESET} All essential entries present")
    
    # Check test files
    print(f"\n{Colors.BOLD}🧪 Tests:{Colors.RESET}")
    test_files = [
        "tests/__init__.py",
        "tests/test_client.py",
    ]
    
    for file in test_files:
        check_file_exists(file, required=False)
    
    # Check data directories exist but are empty (or not committed)
    print(f"\n{Colors.BOLD}📁 Data Directories:{Colors.RESET}")
    data_dirs = ["data/raw", "data/processed"]
    
    for dir_path in data_dirs:
        if Path(dir_path).exists():
            files = list(Path(dir_path).glob('*'))
            if files:
                print(f"  {Colors.YELLOW}⚠{Colors.RESET} {dir_path} contains {len(files)} files (check .gitignore)")
            else:
                print(f"  {Colors.GREEN}✓{Colors.RESET} {dir_path} exists and is empty")
        else:
            print(f"  {Colors.YELLOW}⚠{Colors.RESET} {dir_path} does not exist")
    
    # Final summary
    print("\n" + "=" * 60)
    if all_passed:
        print(f"{Colors.GREEN}{Colors.BOLD}✓ All checks passed! Ready for GitHub!{Colors.RESET}")
        print(f"\nNext steps:")
        print(f"  1. Update placeholders (YOUR_USERNAME, etc.)")
        print(f"  2. Review GITHUB_SETUP.md for publishing instructions")
        print(f"  3. Run: git init && git add . && git commit -m 'Initial commit'")
        return 0
    else:
        print(f"{Colors.RED}{Colors.BOLD}✗ Some issues found. Please review above.{Colors.RESET}")
        print(f"\nReview:")
        print(f"  - Update placeholder text")
        print(f"  - Remove sensitive files")
        print(f"  - Add missing required files")
        return 1


if __name__ == "__main__":
    sys.exit(main())
