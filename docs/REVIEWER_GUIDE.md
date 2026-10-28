# Reviewer guide

Judge the candidate's visible shape against the selected engineering role. Record the required features, the decision, and the supporting observation. Use accompanying drawings or specifications when a review requires thread designation, gear module, material, pressure rating, load capacity, or spring rate.

Start with the [annotation tutorial](ANNOTATION_TUTORIAL.md), which explains every control and provides four complete practice examples.

## Decisions

| Decision | Meaning | Grade |
|---|---|---|
| Shortlist | Every required visible shape feature supports the requested role | 2 |
| Conditional | Plausible, with a specific requirement unverified | 1 |
| Reject | Visible shape conflicts with the request | 0 |
| Cannot assess | Another view or document is needed | null |

Describe the decisive visible feature and identify any additional evidence needed. Some evidence reasons require a note. Check the save status before leaving. Surface markers locate evidence in normalized coordinates. Cutaway displays an uncapped visual slice.

## Pilot and disagreement handling

Start with approximately 20–30 shared cases across tasks and ambiguous forms. Two experts use different IDs without viewing each other's answers. Resolve unclear task wording before scaling up; freeze new instructions if the rubric changes.

Use the comparison command in the README to obtain overlap, descriptive agreement, quadratic-weighted kappa, and a disagreement CSV. Cannot assess is counted separately from numerical kappa. Kappa requires assessable overlap and usable category variation.

For adjudication, inspect the disagreement CSV together and save resolved decisions under a separate adjudicator ID. Preserve the original independent reviews and record the evidence that resolves each disagreement.

## Separate review sections

Task reviews accept the request or document a proposed revision. The coordinator can use those notes to prepare a new protocol. CAD relevance reviews supply candidate-level evaluation labels. Generic knowledge reviews assess scoped class–function relations. Accepted generic priors enter the exported knowledge folder.

Candidate ordering is deterministic. Reviewers inspect neutral IDs, source geometry, task requirements, and their own saved observations. STEP downloads preserve the source metadata. Reviewer identity and authorship use self-attestation.

## Completion and exports

Download the review JSON and keep a backup. Notes, source hashes, timestamps, and prior decisions remain in the revision history. Cannot assess retains a null grade, while an unreviewed case remains pending.

For subsequent retrieval evaluation, use the expanded protocol and source manifest together with the exported judgments. Report task approval, reviewed coverage, assessable coverage, and unresolved cases for each role. Each role contains 1,816 candidates.
