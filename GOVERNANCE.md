<!-- SPDX-FileCopyrightText: 2026 Ryan Madhuwala <rawx18.dev@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Governance

## Purpose

This document defines the governance model of this project, including the roles through which contributors participate in the development, maintenance, and long-term stewardship of the project.

The governance model is intended to establish a transparent and merit-based path for contributors to assume progressively greater responsibility. Authority within the project is based on demonstrated technical competence, sustained contribution, sound judgment, familiarity with the project's architecture and objectives, and a commitment to the long-term health of the project and its community.

The roles described in this document are intended to reflect increasing levels of responsibility rather than status. Advancement between roles is based on demonstrated capability and trust within the project and is not determined solely by the number of contributions, the amount of time an individual has been involved, or organizational affiliation.

The project values technical excellence, constructive collaboration, responsible stewardship, and the sustainable growth of the open-source community.

## Governance Model

The project follows a contributor-led governance model in which responsibility is progressively delegated to individuals who demonstrate sustained technical and community contributions.

The principal contributor roles are **Contributor**, **Core Contributor**, and **Maintainer**.

These roles represent different levels of responsibility within the project. A Contributor participates in the development of the project and builds familiarity with its codebase and development practices. A Core Contributor has demonstrated sufficient technical depth and sustained engagement to take responsibility for meaningful areas of the project and to participate independently in technical review and issue triage. A Maintainer is entrusted with ownership and stewardship of a subsystem or major component and is responsible not only for its technical direction and reliability, but also for contributing to the continued growth and sustainability of the project.

The progression between roles is merit-based. Contributors are expected to demonstrate the capabilities associated with a role before assuming its corresponding responsibilities.

## Contributor

A **Contributor** is an individual who actively participates in the project and is developing familiarity with its architecture, development practices, and objectives.

This role includes individuals making their first contributions as well as contributors who are progressively becoming more familiar with a particular area of the project. Contributions may include source code, documentation, testing, issue reports, issue investigation, bug fixes, examples, design discussions, or other work that materially improves the project.

Contributors are encouraged to develop a broad understanding of the project and to work with existing maintainers and core contributors when addressing issues that require architectural or subsystem-specific knowledge.

A Contributor does not necessarily have responsibility for a particular subsystem and is not expected to independently make decisions affecting the broader technical direction of the project. The primary objective of this stage is to build technical familiarity, establish a consistent contribution history, and demonstrate the ability to work effectively within the project's development and review processes.

## Core Contributor

A **Core Contributor** is an individual who has demonstrated sustained and meaningful involvement in the project and has developed a strong understanding of its architecture, development practices, technical objectives, and project vision.

Core Contributors are expected to be capable of independently working within one or more areas of the project and of providing technically meaningful assistance to the corresponding subsystem. They are expected to understand the purpose and behavior of the components they work on, participate effectively in issue triage, review pull requests, identify regressions and technical risks, and assist other contributors in navigating the project.

A Core Contributor should have sufficient familiarity with the repository to understand how its major components interact and should be able to reason about changes beyond the immediate implementation details of an individual issue or pull request.

Core Contributors may be entrusted with component-level responsibilities and may serve as technical points of contact for particular areas of the project. They are expected to exercise sound judgment in code review, issue prioritization, and technical discussions, while escalating decisions that materially affect the project's architecture or long-term direction when appropriate.

Core Contributor status reflects established trust and technical maturity within the project. It does not necessarily imply formal ownership of a subsystem.

## Maintainer

A **Maintainer** is an individual entrusted with ongoing technical and community stewardship of a subsystem, component, or other significant area of the project.

Maintainers are expected to possess deep technical understanding of the areas for which they are responsible and to be accountable for their continued health, correctness, maintainability, and evolution. A Maintainer should understand not only the implementation of the relevant subsystem but also its dependencies, interfaces, operational considerations, and role within the broader architecture.

Maintainers are responsible for providing technical leadership within their area of ownership. This includes reviewing and guiding significant changes, helping establish technical direction, maintaining quality standards, identifying architectural and operational risks, coordinating work across related components, and ensuring that important issues do not remain unattended.

Maintainer responsibility extends beyond code ownership. Maintainers are stewards of the project and are expected to contribute to its long-term sustainability. This includes helping develop and mentor contributors, improving project documentation and engineering practices, supporting healthy issue and pull request workflows, and participating in activities that increase adoption, community participation, contributor diversity, and overall project traction where appropriate.

A Maintainer is therefore expected to consider both the immediate technical requirements of their subsystem and the long-term interests of the project as a whole.

Maintainer status represents a position of trust and responsibility. It is not granted solely on the basis of technical ability or repository tenure. Individuals entrusted with maintainership are expected to consistently demonstrate sound judgment, reliability, collaborative behavior, and a commitment to the continued development and sustainability of the project.

## Advancement

Advancement between contributor roles is based on demonstrated merit, sustained engagement, technical competence, and the ability to responsibly perform the responsibilities associated with the next role.

There is no fixed minimum number of commits, pull requests, issues, months of participation, or other numerical threshold required for advancement. Quantitative contribution may provide useful evidence of engagement, but advancement is ultimately determined by the quality, consistency, and significance of an individual's contributions and their demonstrated ability to assume additional responsibility.

A Contributor may progress to Core Contributor status after demonstrating a sustained understanding of the project, meaningful technical contributions, effective participation in issue and pull request workflows, and the ability to work independently within relevant areas of the codebase.

A Core Contributor may progress to Maintainer status when they have demonstrated sufficient technical depth, sustained engagement, subsystem-level ownership, sound decision-making, and a continued commitment to both the technical health and broader growth of the project.

Advancement should normally be supported by existing Maintainers familiar with the individual's contributions. The project may use a documented nomination, discussion, or consensus process appropriate to its size and maturity.

## Maintainer Responsibilities

Maintainers collectively safeguard the technical and operational health of the project. Individual Maintainers retain primary responsibility for the areas they own while remaining accountable to the interests of the project as a whole.

Maintainers are expected to make decisions based on technical merit, project objectives, maintainability, security, reliability, user impact, and the long-term interests of the project rather than personal, organizational, or commercial interests.

When a decision affects multiple subsystems or materially changes the project's architecture or direction, the relevant Maintainers should seek broader technical discussion before proceeding.

Maintainers should actively reduce single-person dependencies by documenting systems, sharing knowledge, mentoring contributors, and developing additional ownership within their areas. The long-term objective is to build a resilient community in which responsibility can be shared rather than concentrated in a small number of individuals.

## Decision Making

Technical decisions should generally be made through open discussion and consensus wherever practical.

Routine decisions concerning implementation details may be made by the Maintainer or Core Contributor responsible for the relevant area, provided that the decision is consistent with the project's established architecture and direction.

Decisions with broader architectural, compatibility, security, API, or project-wide implications should involve the relevant Maintainers and affected contributors before implementation.

Disagreement is expected to be resolved through technical discussion based on evidence, project requirements, maintainability, and the long-term interests of the project. The objective of governance is not to establish personal authority but to enable responsible and effective decision-making.

Where consensus cannot reasonably be reached, Maintainers may make a final decision within their area of responsibility, provided that the decision is documented and consistent with the project's principles and broader technical direction. Decisions affecting the overall direction of the project should be discussed among the Maintainers collectively.

## Project Ownership

Ownership within the project is primarily responsibility-oriented rather than exclusive.

A Maintainer may be the primary owner of a subsystem while other contributors remain free to investigate, propose changes, review code, and contribute improvements to that subsystem.

Subsystem ownership exists to ensure that important areas have clear accountability, technical stewardship, and continuity. It should not create unnecessary barriers to contribution or prevent the broader community from participating in the development of the project.

Maintainers are expected to encourage contributions to their areas of ownership and to develop additional contributors capable of assuming responsibility over time.

## Community and Conduct

All participants in the project are expected to act professionally, respectfully, and in the best interests of the project and its community.

Technical disagreement is permitted and encouraged when conducted constructively. Personal attacks, harassment, discrimination, intimidation, or behavior that undermines a healthy contribution environment are not acceptable.

Governance authority must not be used to suppress legitimate technical disagreement, unfairly exclude contributors, or advance interests unrelated to the project.

The project's Code of Conduct, contribution guidelines, and other applicable policies form part of this governance framework.

## Inactive or Resigned Maintainers

Maintainer status carries an expectation of sustained involvement.

A Maintainer who becomes inactive for an extended period may voluntarily step down or may be moved to an inactive or emeritus status by the active Maintainers where necessary to ensure that project ownership remains clear and operational responsibilities remain covered.

A change in employment, organizational affiliation, or other external relationship does not by itself determine contributor status. Governance decisions should be based on an individual's contributions, responsibilities, and continued relationship with the project.

Former Maintainers remain welcome to contribute to the project and may be reconsidered for an active role if they resume sustained participation.

## Governance Evolution

The governance model may evolve as the project grows in contributors, users, technical complexity, and organizational maturity.

Changes to this document should be discussed openly and should preserve the project's commitment to merit-based advancement, transparent decision-making, technical accountability, community health, and long-term sustainability.

As the project grows, additional roles, formal voting procedures, technical steering structures, or other governance mechanisms may be introduced where they provide meaningful value to the community.

## Summary of Roles

The project recognizes three principal levels of responsibility:

**Contributor** represents active participation and continued development of project knowledge.

**Core Contributor** represents sustained technical engagement, broad repository familiarity, effective issue and pull request triage and review, and meaningful responsibility within one or more project components.

**Maintainer** represents subsystem or component ownership, technical leadership, long-term accountability, mentorship, and active stewardship of the project's continued growth and sustainability.

These roles are progressive in responsibility but are not intended to create unnecessary hierarchy. The purpose of the contributor ladder is to make responsibility, expectations, and paths for advancement clear while ensuring that project authority remains grounded in demonstrated merit and trust.