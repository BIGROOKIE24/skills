> **Note:** This repository contains Baidu AI Cloud's official collection of skills for Claude. For information about the Agent Skills standard, see [agentskills.io](https://agentskills.io).

# BCE Skills

Skills are folders of instructions, scripts, and resources that Claude loads dynamically to improve performance on specialized tasks. Skills teach Claude how to complete specific tasks in a repeatable way, whether that's integrating with Baidu AI Cloud services, processing data using BCE-specific workflows, or automating cloud-native tasks.

For more information, check out:
- [Agent Skills Specification](https://agentskills.io/specification)
- [What are skills?](https://support.claude.com/en/articles/12512176-what-are-skills)
- [Using skills in Claude](https://support.claude.com/en/articles/12512180-using-skills-in-claude)
- [How to create custom skills](https://support.claude.com/en/articles/12512198-creating-custom-skills)

# About This Repository

This repository is the official skills collection maintained by **Baidu AI Cloud (BCE)**. It contains skills that demonstrate what's possible with Claude's skills system, with a focus on Baidu AI Cloud ecosystem integration and Chinese language support.

Each skill is self-contained in its own folder with a `SKILL.md` file containing the instructions and metadata that Claude uses. Browse through these skills to get inspiration for your own skills or to understand different patterns and approaches.

## Skill Sets

- [./skills](./skills): Official BCE skill collection
- [./spec](./spec): The Agent Skills specification
- [./template](./template): Skill template for creating new skills

## Try in Claude Code

You can register this repository as a Claude Code Plugin marketplace by running the following command in Claude Code:
```
/plugin marketplace add baidubce/skills
```

Then, to install a specific set of skills:
1. Select `Browse and install plugins`
2. Select `bce-agent-skills`
3. Select the skill set you want
4. Select `Install now`

## Creating a Basic Skill

Skills are simple to create - just a folder with a `SKILL.md` file containing YAML frontmatter and instructions. You can use the **template** in this repository as a starting point:

```markdown
---
name: my-skill-name
description: A clear description of what this skill does and when to use it
---

# My Skill Name

[Add your instructions here that Claude will follow when this skill is active]

## Examples
- Example usage 1
- Example usage 2

## Guidelines
- Guideline 1
- Guideline 2
```

The frontmatter requires only two fields:
- `name` - A unique identifier for your skill (lowercase, hyphens for spaces)
- `description` - A complete description of what the skill does and when to use it

The markdown content below contains the instructions, examples, and guidelines that Claude will follow.

# For Developers

## Branch Strategy

| Branch | Purpose |
|--------|---------|
| **`develop`** | Default branch for all submissions. All new skills and changes should be submitted here via Pull Request. |
| **`main`** | Stable branch. Only updated through reviewed merges from `develop`, and corresponds to official release versions. |

### Workflow

1. **Fork** this repository and create your feature branch from `develop`
2. Commit your changes and push to your fork
3. Open a **Pull Request** targeting the `develop` branch of `baidubce/skills`
4. A **reviewer** will review your PR and merge it into `develop`
5. Periodically, `develop` is merged into `main` to cut a new stable release

> **Note:** Do not submit PRs directly to `main`. All contributions must go through `develop` for review.

# Contributing

We welcome contributions from the community! To add a new skill:

1. Fork this repository
2. Create a feature branch from `develop`
3. Create a new folder under `skills/` with your skill name
4. Add a `SKILL.md` file following the [Agent Skills specification](https://agentskills.io/specification)
5. Add a `LICENSE.txt` file if applicable
6. Submit a Pull Request to the `develop` branch

# License

Skills in this repository are licensed under the Apache 2.0 License unless otherwise noted. See individual skill directories for specific license information.
