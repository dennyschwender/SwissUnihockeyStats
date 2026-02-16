# Security Policy

## Supported Versions

Currently, we are in the initial development phase. Security updates will be provided for:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability within this project, please report it responsibly:

1. **Do NOT** open a public issue
2. Email the maintainers directly (or use GitHub Security Advisories)
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

## Security Best Practices

When using this project:

- **Never commit API credentials** - Use environment variables or config files (gitignored)
- **Validate all input** - Especially when building web applications
- **Keep dependencies updated** - Run `pip list --outdated` regularly
- **Use HTTPS** - The API client defaults to HTTPS
- **Rate limiting** - Implement rate limiting to avoid overwhelming the API
- **Error handling** - Don't expose sensitive information in error messages

## Third-Party Dependencies

This project relies on several third-party packages. We:
- Monitor security advisories for dependencies
- Update dependencies regularly
- Use `pip-audit` to check for known vulnerabilities

Run security checks:
```bash
pip install pip-audit
pip-audit
```

## API Key Security

While the current public endpoints don't require authentication, if you use private endpoints:

- Store API keys in environment variables, not in code
- Use `python-dotenv` for local development
- Add `.env` files to `.gitignore`
- Rotate keys regularly
- Use separate keys for development/production

## Disclosure Policy

- Security issues will be disclosed after a fix is available
- Credit will be given to researchers who report responsibly
- We aim to respond within 48 hours and patch within 7 days for critical issues
