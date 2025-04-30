# Documentation Standards for OPDS-ABS

This guide outlines the documentation standards for the OPDS-ABS project. Following these guidelines ensures consistent, high-quality documentation throughout the codebase.

## Google-Style Docstrings

We use Google-style docstrings across the project. Here's the required format:

```python
def function_name(param1, param2):
    """Brief description of function purpose.

    More detailed explanation that can span multiple lines
    and provide context about what this function does.

    Args:
        param1 (type): Description of first parameter.
        param2 (type): Description of second parameter.

    Returns:
        return_type: Description of return value.

    Raises:
        ExceptionType: When and why this exception might be raised.
    """
    # Function implementation
```

## Documentation Requirements

- **All public classes and methods** must have docstrings
- **First line** must be a brief summary that ends with a period
- **Descriptions** should be clear and concise
- **All parameters** must be documented with their types and descriptions
- **Return values** must be documented with their types and descriptions
- **Exceptions** that might be raised should be documented

## Optional Sections

- **Examples**: For complex functions, provide usage examples
- **Notes**: Additional information that doesn't fit elsewhere
- **References**: Citations or links to relevant resources

## Automated Checking

We use `pydocstyle` to automatically check docstrings. Run the docstring checker with:

```bash
./docstring-check.py
```

For a summary report:

```bash
./docstring-check.py --summary
```

## Common Issues and How to Fix Them

1. **D415 - First line should end with a period**:
   - Ensure the first line of your docstring ends with a period, question mark, or exclamation point

2. **D212 - Multi-line docstring summary should start at the first line**:
   - Place the summary on the first line of the docstring, not the second

3. **D403 - First word of the first line should be capitalized**:
   - Capitalize the first word of the docstring

4. **D200 - One-line docstring should fit on one line**:
   - If your docstring is one line, ensure it doesn't contain newlines

## Integration with CI

Docstring checks are automatically run as part of our GitHub Actions workflow. Pull requests failing the docstring checks will be flagged for review.

## Examples

### Class Docstring

```python
class ExampleClass:
    """Represents an example class for demonstration purposes.

    This class demonstrates proper docstring format for classes in the project.
    It shows how to document class attributes and methods according to our standards.

    Attributes:
        attr1 (str): Description of attribute 1.
        attr2 (int): Description of attribute 2.
    """
```

### Method Docstring

```python
def example_method(param1, param2=None):
    """Process the input parameters and return a transformed result.

    This method shows the proper format for documenting methods with
    optional parameters and exceptions.

    Args:
        param1 (str): The primary input string to process.
        param2 (int, optional): An optional parameter with default None.

    Returns:
        dict: A dictionary containing the processed results.

    Raises:
        ValueError: If param1 is empty.
        TypeError: If param2 is provided but not an integer.

    Example:
        >>> example_method("test", 123)
        {'input': 'test', 'value': 123}
    """
```

## Tools and Resources

- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
- [pydocstyle](http://www.pydocstyle.org/en/stable/) - Tool for checking compliance with Python docstring conventions
