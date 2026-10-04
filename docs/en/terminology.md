# Core terminology

[한국어](../ko/terminology.md)

| Term | Meaning |
| --- | --- |
| Task | User goal, acceptance, ordered skill runs, attempts and assignments in one aggregate. |
| Phase | The current ordered step defined by a skill, with required outcomes and allowed effects. |
| Attempt | One execution or rework attempt; failure does not complete or cancel the goal. |
| Actor | A native observed session or agent, independent of its working directory. |
| Assignment | Bounded work delegated through subagent, session or cross-provider execution. |
| Worker / reviewer / executor | Roles; they do not choose the session or host. |
| Writer lease | Exclusive write coordination for a checkout, with a generation that rejects stale releases. |
| Source | Original native input, tool observation or attributed report. |
| Evidence | A retained source/result used for a specific condition and subject. |
| Approval interpretation | An agent’s action/target interpretation of an exact original quote; it never changes host permissions. |
| Review target | An explicit checkout and observed source snapshot retained for independent review. |
| Stop | The native normal-completion boundary; unfinished owned work requires continuation. |
| TODO | Native display projected from Task state; not another progress authority. |
| Installation / activation | Files and runtime placement / actual use by the connected native host. |

[Core specification](contributing/core-v2-spec.md)
