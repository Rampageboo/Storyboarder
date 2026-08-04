# Contributing to Storyboarder

Thank you for considering a contribution to Storyboarder.

## Before You Start

For bug reports and small documentation corrections, open an issue or pull request directly. For substantial features, architectural changes, or workflow changes, open an issue first so the intended behavior and production use case can be discussed before implementation.

A useful issue should include:

- The problem or production workflow being addressed
- Current behavior
- Expected behavior
- Reproduction steps where applicable
- Screenshots, project examples, or error output when relevant

## Development Setup

```bash
pip install -r requirements.txt
python main.py
```

Storyboarder runs as a pywebview desktop application. Its local FastAPI server is an internal implementation detail.

## Contribution Principles

Contributions should preserve the following project priorities:

- Creator control over automated behavior
- Clear, inspectable, project-local data
- Reproducible file and export workflows
- Backward compatibility for existing projects where practical
- Explicit distinction between shipped functionality and experimental or planned features
- No required cloud service for core storyboard management

## Pull Requests

Keep pull requests focused and describe:

- What changed
- Why the change is needed
- How it was tested
- Any project-data, UI, or compatibility implications

Update documentation when user-facing behavior, project structure, installation, or architecture changes.

## AI-Assisted Features

Proposals for AI-assisted functionality should be optional, reviewable, and transparent. Generated suggestions should not silently overwrite project data or replace explicit creative decisions.

## License

By contributing, you agree that your contributions will be licensed under the repository's MIT License.
