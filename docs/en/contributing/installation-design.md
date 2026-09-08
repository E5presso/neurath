# Installation entry point design
<!-- date: 2026-09-09; synced_from: baseline f69cb6402683bb2e0bfe56ed04c63f808b263f06 plus current working-tree stdio MCP changes; scope: source, not live-host certification -->

[Usage](../usage/index.md) · [Contributing](index.md)


**English** · [한국어](../../ko/contributing/installation-design.md)

The installation flow was simplified using public installation guides reviewed on 2026-09-06.
Neurath uses its existing installation engine; it does not copy the referenced repositories'
installation scripts or instructions.

| Reference | Installation flow reviewed | Applied to Neurath |
| --- | --- | --- |
| [Q00/ouroboros](https://github.com/Q00/ouroboros#quick-start) | A single installation script connects tool preparation and agent initialization | One entry point covers tool preparation, target installation, and diagnostics |
| [garrytan/gstack](https://github.com/garrytan/gstack#install--30-seconds) | A pasteable agent request, source `setup`, and host selection | A copyable installation request, `./setup TARGET`, and explicit host selection |
| [mattpocock/skills](https://github.com/mattpocock/skills#installation-30-second-setup) | Plugin or skill installation followed by project initialization | Separate installation from project document and verification bindings, with clear next steps |

Neurath requires a persistent Python runtime, hooks, and transaction records in addition to skill
files. Copying skills alone does not complete installation. Because the launcher uses an installed
Python path, [uv tool install](https://docs.astral.sh/uv/concepts/tools/) creates a persistent
environment instead of using the temporary `uvx` cache. The
[official uv installer options](https://docs.astral.sh/uv/reference/installer/) disable shell
configuration changes during uv preparation. uv also provisions Python 3.14.

Installation instructions use source obtained from the public repository. From that source,
users run `./setup /target`; after tool installation, they use `neurath setup`. `setup` follows
the existing integrity check → plan creation → application → local diagnostics sequence.
It does not repeat an already authorized installation approval request. Users review host trust
in the host itself.

The existing `install`, `plan`, `apply`, and `wizard` commands remain available. The default profile
is generic. Reconfiguring an existing installation preserves its hosts, profile, and user-edited
bindings. Preview writes no target files and displays only paths, without original file contents.
