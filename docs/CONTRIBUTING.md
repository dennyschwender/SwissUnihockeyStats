# Contributing to SwissUnihockey Statistics Project

Thank you for your interest in contributing! 🏒

## How to Contribute

### Reporting Bugs
- Check if the bug has already been reported in [Issues](../../issues)
- If not, create a new issue with:
  - Clear description of the problem
  - Steps to reproduce
  - Expected vs. actual behavior
  - Your environment (Python version, OS)

### Suggesting Features
- Open an issue with the `enhancement` label
- Describe the feature and its use case
- Check [FEATURE_IDEAS.md](FEATURE_IDEAS.md) for inspiration

### Pull Requests
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Add tests if applicable
5. Ensure code passes linting (`black`, `flake8`)
6. Commit with clear messages
7. Push to your fork
8. Open a Pull Request

## Development Setup

```bash
# Clone your fork
git clone https://github.com/your-username/swissunihockey.git
cd swissunihockey

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install dev dependencies
pip install black flake8 pytest pytest-cov

# Run tests
pytest

# Format code
black .

# Lint code
flake8 .
```

## Code Style

- Follow PEP 8 guidelines
- Use [Black](https://github.com/psf/black) for formatting
- Add docstrings to functions and classes
- Keep functions focused and small
- Write descriptive variable names

## Testing

- Add tests for new features
- Ensure existing tests pass
- Aim for good test coverage
- Use pytest for testing

## Documentation

- Update README.md if adding features
- Add examples to API_USAGE_EXAMPLES.py
- Comment complex logic
- Update GETTING_STARTED.md for user-facing changes

## Project Structure

```
swissunihockey/
├── api/              # API client code
├── scripts/          # Example scripts
├── data/             # Data storage (gitignored)
├── tests/            # Test files
└── docs/             # Additional documentation
```

## Questions?

Feel free to open an issue for questions or reach out to the maintainers.

Thank you for contributing! 🙏
