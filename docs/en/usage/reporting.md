<!-- updated: 2026-09-14 | synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Share a problem in Neurath itself

While investigating the saved filter in your web application, an agent might encounter a separate problem in Neurath's working support. The filter bug belongs to your application. A defect in a packaged Neurath component may be useful to report to Neurath's maintainers after the agent establishes a generic reproduction.

> If this is a common Neurath defect, prepare a report that explains the harness behavior without exposing this project's code, identity, or conversation. Show me what will be shared and follow my reporting choice.

The working support Neurath installs around an agent is its **harness**. Reporting covers defects and improvements in that common harness, plus separately approved proposals to contribute reusable improvements. It is optional and does not determine whether your filter investigation can continue.

## Choose whether common reports may be sent

Automatic public reporting starts disabled pending your explicit choice. During onboarding, an agent can ask once whether you consent to common Neurath defect and improvement reports. If you agree, that preference is saved for the local project and can be used by its sessions and linked worktrees. If you decline, the agent should not repeatedly ask without a new indication from you.

Supported hooks remind the agent of the choice and reporting scope. They do not collect reports or send them. Even with consent, the agent must identify a common harness issue, prepare a suitable report, and perform the privacy review before submission.

You can withdraw consent for future common reports. Withdrawal does not remove issues already published.

## Review the problem without exporting the project

The report should explain expected behavior, observed behavior, a generic reproduction, and the proposed correction. The agent checks that the component is part of Neurath's packaged content and that the report is genuinely about common behavior. A locally customized component may instead need a contribution proposal.

Project code, custom assets, names, paths, logs, conversations, credentials, business data, and attachments stay out of the public report. Known patterns are checked automatically, but the agent still needs to read the meaning of the text for private information. Passing a pattern scan is not a privacy guarantee.

The prepared draft has fixed content. If its content changes, the agent prepares a new draft rather than treating an earlier review as approval of different text. A useful result gives you the draft's purpose and the destination before publication.

## Approve a project-specific contribution separately

Suppose the investigation suggests a reusable improvement based on how this project organizes its checks. That project-specific idea is not covered by blanket consent for common harness reports. The agent must first turn it into a standalone proposal with private details removed, then obtain your approval for that exact contribution draft.

A request to prepare a proposal can stop at the reviewable draft. Consent for common reports does not silently authorize contributing customized project work.

## Confirm the public result

Reports are sent to [Neurath's public issue tracker](https://github.com/E5presso/neurath/issues). The agent verifies the created issue's title and body against the prepared report before calling submission complete.

If publication becomes uncertain—for example, the connection fails after the remote service may have accepted the issue—the agent must inspect the existing result before any retry. It can reconcile a matching issue with the local draft instead of creating a duplicate. Until that readback succeeds, the result remains uncertain.

A submitted Neurath issue is a separate outcome from fixing your application. The saved-filter task remains open until its own requested behavior has been demonstrated. For draft fields, consent records, and recovery actions, see the [reporting reference](../contributing/reporting-reference.md).

[한국어](../../ko/usage/reporting.md)
