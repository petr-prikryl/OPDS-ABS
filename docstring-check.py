#!/usr/bin/env python
"""Script to check docstrings across the OPDS-ABS codebase.

This script runs pydocstyle checks against the codebase and produces a readable summary
of missing or malformed docstrings. It provides options for checking specific files or
directories and can generate detailed or summary reports.
"""
import os
import sys
import argparse
import subprocess
from collections import defaultdict
import re

# Regular expressions to extract information from pydocstyle output
FILE_REGEX = re.compile(r'^(.+?):(\d+)')  # Matches filename and line number
ERROR_REGEX = re.compile(r'^\s+([A-Z]\d+): (.+)$')  # Matches error code and message

def parse_args():
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(description='Check docstrings in Python files')
    parser.add_argument('path', nargs='?', default='opds_abs',
                      help='Path to directory or file to check (default: opds_abs)')
    parser.add_argument('--summary', '-s', action='store_true',
                      help='Display only a summary of issues')
    parser.add_argument('--verbose', '-v', action='store_true',
                      help='Display detailed information about issues')
    parser.add_argument('--errors', '-e', action='store_true',
                      help='Show only errors, not file paths')
    parser.add_argument('--fix-missing', '-f', action='store_true',
                      help='Generate template docstrings for missing ones (outputs to stdout)')
    return parser.parse_args()

def run_pydocstyle(path):
    """Run pydocstyle on the specified path.

    Args:
        path (str): Path to file or directory to check

    Returns:
        tuple: (return_code, stdout_output, stderr_output)
    """
    command = ['pydocstyle', path]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate()
    return process.returncode, stdout, stderr

def parse_pydocstyle_output(output):
    """Parse pydocstyle output into a structured format.

    Args:
        output (str): Output from pydocstyle command

    Returns:
        dict: Dictionary mapping files to lists of error information
    """
    results = defaultdict(list)
    current_file = None
    current_line = None

    for line in output.split('\n'):
        file_match = FILE_REGEX.match(line)
        if file_match:
            current_file = file_match.group(1)
            current_line = file_match.group(2)
            continue

        error_match = ERROR_REGEX.match(line)
        if error_match and current_file:
            error_code = error_match.group(1)
            error_message = error_match.group(2)
            results[current_file].append({
                'line': current_line,
                'code': error_code,
                'message': error_message
            })

    return results

def display_results(results, args):
    """Display the processed results.

    Args:
        results (dict): Dictionary mapping files to lists of error information
        args (argparse.Namespace): Command line arguments
    """
    if not results:
        print("\n✅ All checked files have proper docstrings!")
        return

    total_files = len(results)
    total_errors = sum(len(errors) for errors in results.values())

    error_types = defaultdict(int)
    for file_errors in results.values():
        for error in file_errors:
            error_types[error['code']] += 1

    # Define error code meanings
    error_meanings = {
        'D100': 'Missing docstring in public module',
        'D101': 'Missing docstring in public class',
        'D102': 'Missing docstring in public method',
        'D103': 'Missing docstring in public function',
        'D105': 'Missing docstring in magic method',
        'D107': 'Missing docstring in __init__ method',
        'D200': 'One-line docstring should fit on one line',
        'D201': 'No blank lines allowed before docstring',
        'D202': 'No blank lines allowed after docstring',
        'D205': '1 blank line required between summary and description',
        'D207': 'Docstring is under-indented',
        'D208': 'Docstring is over-indented',
        'D209': 'Multi-line docstring closing quotes on separate line',
        'D210': 'No whitespace allowed surrounding docstring text',
        'D212': 'Multi-line docstring summary should start at the first line',
        'D213': 'Multi-line docstring summary should start at the second line',
        'D400': 'First line should end with a period',
        'D401': 'First line should be in imperative mood',
        'D402': 'First line should not be the function\'s signature',
        'D403': 'First word of the first line should be capitalized',
        'D404': 'First word of the docstring should not be "This"',
        'D405': 'Section name should be properly formatted',
        'D406': 'Section name should end with a colon',
        'D407': 'Missing dashed underline after section',
        'D408': 'Section underline should be in the line following the section name',
        'D409': 'Section underline should match the length of its name',
        'D410': 'Missing blank line after section',
        'D411': 'Missing blank line before section',
        'D412': 'No blank lines allowed between a section header and its content',
        'D413': 'Missing blank line after last section',
        'D414': 'Section has no content',
        'D415': 'First line should end with a period, question mark, or exclamation point',
        'D416': 'Section name should end with a colon',
        'D417': 'Missing argument descriptions in the docstring'
    }

    print(f"\n📊 Docstring Check Summary:")
    print(f"{'='*80}")
    print(f"Files with issues: {total_files}")
    print(f"Total issues found: {total_errors}")
    print(f"\n🔍 Issues by type:")

    for code, count in sorted(error_types.items(), key=lambda x: x[1], reverse=True):
        meaning = error_meanings.get(code, "Unknown issue")
        print(f"  {code}: {count} occurrences - {meaning}")

    if not args.summary:
        print(f"\n📝 Detailed issues:")
        print(f"{'='*80}")
        for file_path, errors in sorted(results.items()):
            print(f"\n📄 {file_path} ({len(errors)} issues)")
            for error in errors:
                print(f"  Line {error['line']}: {error['code']} - {error['message']}")

def generate_template_docstrings(results):
    """Generate template docstrings for missing docstrings.

    Args:
        results (dict): Dictionary mapping files to lists of error information
    """
    # This is a placeholder for functionality that would parse the Python files
    # and generate template docstrings based on function/class signatures
    print("\n🔧 Docstring Template Generator")
    print("="*80)
    print("Note: This feature would generate template docstrings based on your code.")
    print("For now, here's a suggested template to follow:")

    print("""
def function_name(param1, param2):
    \"\"\"Brief description of function purpose.

    More detailed explanation that can span multiple lines
    and provide context about what this function does.

    Args:
        param1 (type): Description of first parameter.
        param2 (type): Description of second parameter.

    Returns:
        return_type: Description of return value.

    Raises:
        ExceptionType: When and why this exception might be raised.
    \"\"\"
    """)

    # List files that need docstrings the most
    files_by_issues = sorted(results.items(), key=lambda x: len(x[1]), reverse=True)
    if files_by_issues:
        print("\nFiles that need the most attention:")
        for file_path, errors in files_by_issues[:5]:
            print(f"  {file_path}: {len(errors)} missing/malformed docstrings")

    # In a real implementation, we would:
    # 1. Parse each Python file with missing docstrings
    # 2. Extract function/method signatures
    # 3. Generate appropriate template docstrings based on parameters
    # 4. Suggest addition of these docstrings to the files

def main():
    """Run the main script to check docstrings."""
    args = parse_args()
    return_code, stdout, stderr = run_pydocstyle(args.path)

    if stderr:
        print(f"Error running pydocstyle: {stderr}")
        sys.exit(1)

    results = parse_pydocstyle_output(stdout)
    display_results(results, args)

    if args.fix_missing:
        generate_template_docstrings(results)

    # Return exit code based on whether issues were found
    return 0 if not results else 1

if __name__ == "__main__":
    sys.exit(main())
