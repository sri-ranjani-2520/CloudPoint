# CloudPoint — Campus Complaint Management System

## 1. Project Overview

CloudPoint is a web-based Campus Complaint Management System designed to provide a centralized platform for students to submit campus-related complaints and track their progress, while administrators can review, manage, and update those complaints.

The system aims to make complaint handling more organized, transparent, accessible, and accountable. It replaces an informal or manual complaint-handling process with a structured workflow in which every complaint receives a unique identifier and has a clearly defined status.

CloudPoint consists of two primary portals:

- **Student Portal:** Enables students to submit complaints, receive complaint IDs, and track the current status of their complaints.
- **Administrator Portal:** Enables authorized administrators to review complaints, search and filter records, inspect complaint details, and manage complaint statuses.

The application must support the complete complaint lifecycle, from initial submission to resolution or rejection, while maintaining accurate records and providing clear feedback to users.

## 2. Project Objectives

The primary objectives of CloudPoint are:

1. Provide a centralized platform for campus complaint submission and management.
2. Allow students to submit complaints without navigating a complicated process.
3. Generate a unique identifier for every successfully submitted complaint.
4. Enable students to check complaint status independently.
5. Provide administrators with an organized interface for managing complaints.
6. Support efficient complaint discovery through search and filtering.
7. Maintain accurate complaint information and timestamps.
8. Ensure that administrative operations are restricted to authenticated administrators.
9. Provide clear status information and rejection reasons to improve transparency.
10. Maintain consistency between student-facing information and administrator-managed records.
11. Provide a responsive, accessible, and consistent user experience.
12. Keep the initial scope focused on essential complaint-management functionality.

## 3. User Roles

### 3.1 Student

Students are the primary users who report campus-related issues.

Students can:

- Access the complaint submission page.
- Enter their identification and complaint information.
- Submit a complaint.
- Receive a unique complaint ID.
- Track an existing complaint using its ID.
- View the complaint's current status.
- View relevant complaint details.
- Read the reason for rejection when a complaint has been rejected.

The initial version does not require students to create accounts or authenticate before submitting or tracking complaints. Complaint tracking is performed using the generated complaint ID.

### 3.2 Administrator

Administrators are responsible for reviewing and managing submitted complaints.

Administrators can:

- Log in to the administration portal.
- Log out of the application.
- View complaint statistics.
- View submitted complaints.
- Search complaints.
- Filter complaints by category and status.
- Inspect complete complaint details.
- Update complaint statuses.
- Provide a reason when rejecting a complaint.
- Ensure that complaint records are managed consistently.

Administrative functionality must remain inaccessible to unauthenticated users.

## 4. Student Portal Features

### 4.1 Landing Page

The landing page serves as the main entry point to CloudPoint.

It must provide clear navigation to:

- Submit a Complaint
- Track a Complaint
- Administrator Login

The page should introduce the purpose of CloudPoint and guide students toward the appropriate action.

The interface should have clear navigation, readable content, consistent styling, and layouts suitable for both desktop and mobile screens.

### 4.2 Complaint Submission

Students must be able to submit complaints through a structured form.

The form must collect the following information:

| Field | Description |
|---|---|
| Student Name | Name of the student submitting the complaint |
| Registration Number | Student's institutional registration number |
| Complaint Title | Brief summary of the reported issue |
| Category | Classification of the complaint |
| Description | Detailed explanation of the issue |
| Location | Campus location where the issue occurred |

All required fields must be validated before a complaint is accepted.

The form should clearly identify mandatory fields and display understandable validation messages when information is missing or invalid.

The student should receive appropriate feedback while the submission is being processed, preventing uncertainty about whether the complaint has been submitted successfully.

### 4.3 Complaint Categories

Every complaint must belong to one of the following predefined categories:

| Category | Purpose |
|---|---|
| Hostel | Issues concerning hostel facilities, accommodation, or related services |
| Academic | Issues concerning academic activities, teaching, or academic administration |
| Infrastructure | Issues concerning buildings, equipment, facilities, or campus infrastructure |
| Transport | Issues concerning campus transportation and related services |
| Cleanliness | Issues concerning sanitation, waste management, and cleanliness |
| Other | Complaints that do not fit into the predefined categories |

Students must select a valid category when submitting a complaint.

The category must be stored with the complaint and made available for administrative filtering.

Only the predefined categories should be accepted in the initial version.

### 4.4 Unique Complaint ID Generation

Every successfully submitted complaint must receive a unique complaint ID.

The complaint ID must:

- Be generated automatically.
- Be unique across all complaint records.
- Be assigned only after the submission passes validation.
- Be associated with the saved complaint.
- Be displayed to the student after successful submission.
- Be usable for retrieving the complaint through the tracking feature.

Students must not be allowed to choose or modify their complaint IDs.

The identifier should be sufficiently unpredictable to reduce the risk of unauthorized discovery of other complaints.

### 4.5 Submission Confirmation

After successful submission, the application must display a confirmation message.

The confirmation must include:

- A clear indication that the complaint was submitted successfully.
- The generated complaint ID.
- Instructions to retain the ID for future tracking.
- An option to proceed to the complaint tracking page.

The application must display this confirmation only after the complaint has been successfully recorded.

If submission fails, the application must explain the failure and allow the student to correct the input or retry the operation as appropriate.

### 4.6 Complaint Tracking

Students must be able to track complaints without logging in.

The tracking interface must provide an input field for the complaint ID and an action to retrieve the corresponding complaint.

For a valid complaint ID, the application must display the relevant complaint information, including:

- Complaint ID
- Complaint title
- Category
- Description
- Location
- Submission timestamp
- Current status
- Rejection reason, when applicable

The current status must reflect the latest status saved by an administrator.

For example, if a complaint initially has the status `Submitted` and is subsequently changed to `In Progress`, the tracking page must display `In Progress` when the complaint is retrieved again.

The application must not rely solely on information retained in the browser from the original submission.

### 4.7 Tracking Error Handling

The tracking feature must handle invalid and nonexistent complaint IDs.

It must distinguish between:

- An empty complaint ID.
- A malformed complaint ID.
- A complaint ID that does not correspond to an existing record.
- A failed request caused by a temporary application or connectivity problem.

The interface must provide a clear error message for each relevant situation and allow the student to attempt the operation again.

It must not display unrelated complaint information when a requested complaint cannot be found.

### 4.8 Student-Facing Status Information

The student portal must display the latest status using a readable label.

When applicable, the student should also be able to read the administrator's rejection reason.

Complaint information presented to students should be limited to the information necessary for tracking their complaints. Unnecessary sensitive information must not be exposed.

## 5. Administrator Portal Features

### 5.1 Administrator Login

The application must provide a dedicated administrator login page.

The login form must include:

- Username
- Password
- Login action
- Validation and authentication feedback

The system must verify administrator credentials before granting access to protected administrative functionality.

Invalid credentials must produce an appropriate error message without revealing sensitive authentication details.

Passwords must not be stored or handled as plaintext credentials.

The initial administrator account must be provisioned through a controlled setup process rather than being exposed through the student-facing interface.

### 5.2 Administrator Session and Logout

After a successful login, the administrator must be able to access the administration portal without repeatedly authenticating during the active session.

The system must support logout.

After logout, protected administrative operations must no longer be accessible using the terminated session.

Administrative pages must not become accessible merely because a user manually navigates to their URLs or modifies frontend controls.

The backend must verify administrator authentication for every protected operation.

### 5.3 Administrator Dashboard

The administrator dashboard must provide an overview of the current complaint workload.

It must display the following statistics:

| Statistic | Description |
|---|---|
| Total Complaints | Total number of recorded complaints |
| Submitted | Complaints awaiting review |
| Under Review | Complaints currently being reviewed |
| In Progress | Complaints currently being addressed |
| Resolved | Complaints marked as resolved |
| Rejected | Complaints that have been rejected |

The dashboard statistics must be based on the current complaint records.

Every complaint must contribute to exactly one of the five status counts. Consequently, the sum of the status counts must equal the total complaint count.

The dashboard must reflect updates made to the underlying complaint records instead of displaying hardcoded or outdated statistics.

The initial version should focus on clear statistical summaries rather than advanced analytics.

### 5.4 Complaint Listing

Administrators must be able to view submitted complaints in an organized management interface.

The complaint listing should display the following information:

- Complaint ID
- Complaint title
- Student registration number
- Category
- Current status
- Submission timestamp
- Last modification timestamp
- Action to view complaint details

The listing must be easy to scan and should make important information, particularly complaint ID and status, readily visible.

Long descriptions may be shortened in the listing and displayed in full in the complaint details view.

The interface must provide a clear empty state when no complaints match the current query or filters.

### 5.5 Complaint Search

Administrators must be able to search complaint records using:

- Complaint ID
- Complaint title
- Student registration number

Search should support partial text matches where appropriate and should not depend exclusively on exact capitalization.

Search results must include all matching records that satisfy the active search and filter criteria.

Searching must remain correct even when the number of complaints grows beyond the records visible on a single page.

The application must treat the search input as data and must not interpret it as executable database instructions.

### 5.6 Complaint Filtering

Administrators must be able to filter the complaint list by category and status.

**Category filter options:**

- All Categories
- Hostel
- Academic
- Infrastructure
- Transport
- Cleanliness
- Other

**Status filter options:**

- All Statuses
- Submitted
- Under Review
- In Progress
- Resolved
- Rejected

The category and status filters must work independently and together.

For example, an administrator must be able to display only Infrastructure complaints that are currently In Progress.

Search criteria and filters must work together rather than overriding one another unexpectedly.

Administrators must be able to clear the applied filters and return to the unfiltered complaint list.

### 5.7 Complaint Details View

Administrators must be able to open any complaint and inspect its complete details.

The detail view must include:

- Complaint ID
- Student name
- Student registration number
- Complaint title
- Category
- Full description
- Location
- Current status
- Creation timestamp
- Last modification timestamp
- Rejection reason, when applicable

The detail view must provide the information necessary to understand the reported issue before making a status decision.

A dedicated details view should keep complaint inspection and status management organized rather than overcrowding the main listing.

### 5.8 Complaint Status Management

Administrators must be able to update the status of a complaint.

The supported statuses are:

1. Submitted
2. Under Review
3. In Progress
4. Resolved
5. Rejected

The status update interface must display the current status and provide controls for selecting a new valid status.

A successful update must:

- Modify the complaint's current status.
- Update its modification timestamp.
- Preserve the rest of the complaint information.
- Return or display the updated complaint information.
- Ensure that subsequent student tracking requests show the latest status.
- Ensure that the dashboard statistics reflect the new status.

Invalid status values must be rejected.

For the initial version, an administrator may select any valid status. More restrictive rules governing permitted transitions can be introduced later if required by institutional policy.

### 5.9 Rejection Reason Management

When an administrator changes a complaint's status to `Rejected`, a rejection reason must be provided.

The reason must:

- Be mandatory for a rejection.
- Contain meaningful, non-empty text.
- Be validated before the status update is accepted.
- Be stored with the complaint.
- Be available in the administrator's complaint details view.
- Be displayed to the student when tracking the rejected complaint.

A rejection must not be accepted if its reason is missing or contains only whitespace.

When a previously rejected complaint is subsequently moved to another status, the application may clear its current rejection reason. However, the handling of the previous rejection should remain consistent with any historical records maintained by the system.

### 5.10 Administrative Operation Feedback

The administrator interface must display appropriate feedback for management operations.

Examples include:

- Complaint retrieved successfully.
- Complaint status updated successfully.
- A valid rejection reason is required.
- The selected complaint could not be found.
- The current session is no longer authorized.
- No complaints match the selected filters.
- The requested operation failed and can be retried.

An unsuccessful operation must not be presented as successful.

## 6. Complaint Status Lifecycle

CloudPoint must use a consistent set of statuses to describe the complaint lifecycle.

### 6.1 Submitted

The complaint has passed validation and has been successfully recorded.

Every new complaint must start in this state.

### 6.2 Under Review

An administrator is examining the complaint to understand the issue and determine the appropriate action.

### 6.3 In Progress

The complaint is being actively addressed.

### 6.4 Resolved

The complaint has been marked as addressed.

### 6.5 Rejected

The administrator has declined the complaint and supplied a reason explaining the decision.

### 6.6 Status Consistency

The application must ensure that the status shown in all relevant views is consistent with the current saved complaint record.

For example:

1. A student submits a complaint.
2. The complaint receives the status `Submitted`.
3. An administrator changes the status to `Under Review`.
4. The complaint record is updated.
5. The administrator dashboard reflects the change.
6. The student retrieves the complaint and sees `Under Review`.

The current status must not be updated only in the browser or only in one interface.

## 7. Complaint Data and Record Management

### 7.1 Persistent Complaint Records

Each complaint must have a persistent record containing the information submitted by the student and the fields maintained by the application.

The record must remain available after the application is restarted.

The application must not depend on browser memory or temporary variables to retain complaints.

### 7.2 Creation and Modification Timestamps

Each complaint must record:

- **Creation timestamp:** When the complaint was successfully created.
- **Modification timestamp:** When the complaint was last modified.

The creation timestamp must remain unchanged when the complaint status is updated.

The modification timestamp must be updated whenever a supported modification is successfully applied.

Timestamps must be recorded consistently and displayed in a readable format.

### 7.3 Record Integrity

The system must preserve complaint data accurately.

It must ensure that:

- Every complaint has a unique identifier.
- Every complaint has one valid current status.
- Every complaint has one valid category.
- Required complaint information is present.
- Failed validation does not create an accepted complaint.
- Invalid updates do not corrupt existing records.
- Status updates do not unintentionally overwrite unrelated complaint fields.
- Dashboard statistics are calculated from the actual complaint records.

### 7.4 Status Modification Accountability

Every successful modification must be associated with the relevant complaint and its modification timestamp.

The application should preserve enough information to explain the current state of a complaint and, where status history is maintained, the sequence of previous status decisions.

Status history is useful for accountability and future auditing, but it should not complicate the essential student submission and tracking workflows.

## 8. Validation Requirements

Validation must be applied consistently across all features.

### 8.1 Submission Validation

The system must reject submissions with:

- Missing student name.
- Missing registration number.
- Missing complaint title.
- Missing category.
- Missing description.
- Missing location.
- A category outside the approved list.
- Input values that exceed the defined length limits.
- Malformed request data.

The system should trim unnecessary leading and trailing whitespace before evaluating text fields.

Registration-number validation should follow configurable institutional rules rather than assuming a universal format.

### 8.2 Complaint ID Validation

Complaint tracking and administrative operations must validate complaint identifiers before attempting to process them.

A malformed identifier should produce an appropriate validation response. An identifier that is syntactically valid but does not refer to an existing complaint should produce a not-found response.

### 8.3 Status Validation

Only the five supported status values may be stored as current complaint statuses.

A request containing an unsupported status must be rejected without changing the complaint.

### 8.4 Rejection Validation

A complaint cannot enter the `Rejected` state without a valid rejection reason.

This rule must be enforced even when a request bypasses the graphical interface.

### 8.5 Authentication Validation

Every administrative operation must verify that the current request belongs to an authenticated administrator.

Hiding an administrative button or page from an unauthenticated user is not sufficient authorization.

## 9. Security and Privacy Requirements

CloudPoint handles student identifiers and complaint information. The application must therefore apply appropriate access restrictions and protect information from unnecessary disclosure.

Required safeguards include:

- Secure administrator authentication.
- Password hashing instead of plaintext password storage.
- Server-side authorization for administrative operations.
- Protected sessions and a working logout mechanism.
- Validation of all user-supplied data.
- Safe handling of search input.
- Safe rendering of student-submitted text.
- Protection against cross-site request forgery for session-authenticated state-changing requests.
- Restricted disclosure of student information in public tracking responses.
- Clear separation between student-accessible and administrator-only functionality.
- Appropriate handling of failed authentication and unauthorized requests.

Student tracking should expose only the complaint information necessary for the intended tracking workflow. It must not provide unrestricted access to administrative lists or unrelated student records.

Security checks must be enforced by the application handling the request, not merely by frontend controls.

## 10. User Interface and Accessibility Requirements

### 10.1 Consistent Visual Design

All pages must follow a common visual design system.

This includes consistent:

- Typography.
- Colors.
- Spacing.
- Buttons.
- Form controls.
- Navigation.
- Cards and content containers.
- Error and success messages.
- Complaint status indicators.

The interface should be professional, readable, and appropriate for a campus administration system.

### 10.2 Responsive Design

The application must remain usable on laptop and mobile screens.

Responsive behavior must cover:

- Navigation.
- Complaint forms.
- Tracking information.
- Administrator dashboard cards.
- Search and filter controls.
- Complaint management tables.
- Complaint detail views.
- Login forms and confirmation messages.

Wide complaint tables should use a suitable narrow-screen presentation rather than forcing the entire interface to overflow uncontrollably.

### 10.3 Loading States

The application should provide visible feedback while requests are being processed.

Examples include complaint submission, tracking requests, dashboard loading, complaint listing, authentication, and status updates.

Duplicate submission should be discouraged while a request is in progress, and the final result must depend on the server's response.

### 10.4 Error and Empty States

The application must provide clear messages when:

- Required fields are missing.
- Submitted data is invalid.
- A complaint does not exist.
- Authentication fails.
- The user lacks permission.
- No complaints match the current filters.
- A request fails.
- An unexpected problem occurs.

The user should be able to understand the issue without seeing internal diagnostic details.

### 10.5 Accessibility

The application should provide:

- Proper labels for form fields.
- Keyboard-accessible controls.
- Visible focus indicators.
- Readable text and adequate contrast.
- Meaningful status labels that do not rely on color alone.
- Clear associations between validation messages and their respective fields.
- Navigation that remains understandable across screen sizes.

## 11. Dashboard and Data Accuracy Rules

The administrator dashboard must accurately reflect current complaint records.

The following relationships must remain true:

- Total complaints equals the number of recorded complaints.
- Every complaint belongs to exactly one current status.
- The sum of Submitted, Under Review, In Progress, Resolved, and Rejected equals Total Complaints.
- A successful status change updates the corresponding status count.
- A complaint must not be counted under multiple current statuses.
- A failed status update must not alter the displayed statistics as though it had succeeded.
- Empty datasets must produce meaningful zero values rather than errors.

Search and filter operations must not accidentally change the underlying complaint records.

## 12. End-to-End User Workflows

### 12.1 Student Complaint Submission Workflow

1. The student opens CloudPoint.
2. The student navigates to the complaint submission page.
3. The student enters their name and registration number.
4. The student provides the complaint title, category, description, and location.
5. The student submits the form.
6. The application validates the submission.
7. The complaint is recorded with a unique complaint ID and the status `Submitted`.
8. The student sees the confirmation and complaint ID.
9. The student retains the ID for tracking.

**Expected result:** The complaint is stored successfully and can be retrieved using the generated ID.

### 12.2 Student Tracking Workflow

1. The student opens the tracking page.
2. The student enters the complaint ID.
3. The application retrieves the corresponding complaint.
4. The tracking page displays the relevant details and latest status.
5. If the complaint has been rejected, its rejection reason is displayed.
6. If the complaint cannot be found, an appropriate message is displayed.

**Expected result:** The student can retrieve the correct complaint and understand its current state.

### 12.3 Administrator Management Workflow

1. The administrator opens the login page.
2. The administrator enters valid credentials.
3. The application authenticates the administrator.
4. The administrator opens the dashboard.
5. The dashboard displays current complaint statistics.
6. The administrator searches or filters the complaint list.
7. The administrator opens a complaint.
8. The administrator inspects its details.
9. The administrator selects a new status.
10. If the new status is `Rejected`, the administrator supplies a rejection reason.
11. The application validates and saves the update.
12. The dashboard reflects the updated status counts.
13. The student can retrieve the complaint and see the latest status.
14. The administrator logs out when finished.

**Expected result:** The complaint is managed securely and consistently across the administrator and student interfaces.

## 13. Testing and Acceptance Criteria

CloudPoint must be tested against its main user workflows and data-integrity rules.

### 13.1 Student Submission Tests

- A valid complaint can be submitted successfully.
- A missing required field is rejected.
- An invalid category is rejected.
- A unique complaint ID is generated.
- The initial status is `Submitted`.
- The confirmation displays the correct complaint ID.
- A failed submission does not create an accepted complaint.
- Repeated successful submissions receive distinct IDs.

### 13.2 Student Tracking Tests

- A valid complaint ID returns the correct complaint.
- A nonexistent complaint ID returns an appropriate not-found result.
- A malformed or empty ID is handled appropriately.
- The latest status is displayed.
- A rejection reason is displayed for rejected complaints.
- Unrelated complaint information is not returned.

### 13.3 Authentication and Authorization Tests

- Valid administrator credentials permit login.
- Invalid credentials are rejected.
- Logout terminates the authenticated session.
- Unauthenticated users cannot list or manage complaints through protected administrative operations.
- Direct requests to administrative endpoints are protected.
- Unauthorized requests do not modify complaint data.

### 13.4 Complaint Management Tests

- Administrators can list complaints.
- Search works by complaint ID.
- Search works by title.
- Search works by registration number.
- Category filtering works.
- Status filtering works.
- Combined search and filters work.
- Complaint details are displayed correctly.
- Valid status updates are persisted.
- Invalid statuses are rejected.
- Rejection without a valid reason is rejected.
- Rejection with a valid reason is accepted.
- Student tracking reflects successful status changes.

### 13.5 Persistence and Dashboard Tests

- Complaint records remain available after the application restarts.
- Creation timestamps remain unchanged after status updates.
- Modification timestamps change after successful modifications.
- Dashboard counts match stored complaint records.
- The sum of all status counts equals the total number of complaints.
- Failed operations do not leave inconsistent records.

### 13.6 User Interface Tests

- Forms display validation messages.
- Success messages appear after successful operations.
- Loading indicators appear during requests.
- Empty states are displayed when no records match.
- Errors are understandable and recoverable where appropriate.
- The major student and administrator workflows remain usable on laptops and mobile screens.
- Form controls and navigation are accessible using a keyboard.

Test results should document the scenario, expected outcome, actual outcome, and pass/fail status.

## 14. Project Scope

### 14.1 Included in the Initial Version

The initial release must include:

- Landing page and navigation.
- Student complaint submission.
- Complaint ID generation.
- Submission confirmation.
- Student complaint tracking.
- Complaint category management.
- Complaint status management.
- Administrator login and logout.
- Administrator dashboard statistics.
- Complaint listing.
- Complaint search.
- Category and status filters.
- Complaint detail views.
- Complaint status updates.
- Mandatory rejection reasons.
- Creation and modification timestamps.
- Input validation and error handling.
- Persistent complaint records.
- Access restrictions for administrative operations.
- Responsive and accessible user interfaces.
- Automated or documented tests for essential workflows.
- Documentation of the system's behavior and completion criteria.

### 14.2 Explicitly Excluded from the Initial Version

The following features are outside the scope of the initial release:

- Email notifications.
- SMS notifications.
- Advanced analytics dashboards.
- File attachments.
- Image attachments.
- Native Android or iOS applications.
- Complaint priority management.
- Machine-learning-based complaint trend analysis.
- AI-based complaint categorization.
- Geo-tagged complaint verification.

These features may be considered in future versions but must not be treated as prerequisites for completing the initial application.

## 15. Future Enhancements

After the essential complaint-management workflow is stable, CloudPoint may be extended with additional capabilities.

Potential enhancements include:

- Notification services for complaint updates.
- Complaint status history and administrative audit trails.
- Advanced reporting and analytics.
- Complaint priority and escalation rules.
- File and image uploads.
- Student authentication and personalized complaint history.
- Additional administrator roles and permissions.
- Bulk complaint-management operations.
- Institutional reporting and export facilities.
- Integration with campus information systems.
- Deployment to a cloud environment.

These enhancements must be evaluated separately and should not delay the initial release.

## 16. Definition of Done

The initial version of CloudPoint is considered complete when all the following conditions are met:

1. A student can submit a valid complaint.
2. Every successfully submitted complaint receives a unique ID.
3. The complaint is saved with the initial status `Submitted`.
4. The student receives a confirmation containing the complaint ID.
5. The student can retrieve the correct complaint using that ID.
6. Invalid and nonexistent complaint IDs are handled correctly.
7. An administrator can log in and log out securely.
8. Administrative operations require authenticated authorization.
9. Administrators can view all complaints.
10. Administrators can search and filter complaints.
11. Administrators can inspect complete complaint details.
12. Administrators can update complaint statuses.
13. A complaint cannot be rejected without a valid reason.
14. Student tracking reflects the latest saved status.
15. Creation and modification timestamps are maintained accurately.
16. Dashboard statistics match the current complaint records.
17. Complaint records persist after application restarts.
18. Input validation and error handling work across all major workflows.
19. The main interfaces are responsive and accessible.
20. Essential test cases have been executed and their results documented.
21. The required student and administrator workflows can be demonstrated successfully.
22. Features explicitly excluded from the initial version are not required for acceptance.

## 17. Project Principle

CloudPoint should prioritize **correctness, data integrity, security, usability, and workflow completeness** over unnecessary complexity.

Every complaint must be uniquely identifiable, every status update must be reflected consistently, and every administrative operation must be authorized.

The student experience should remain simple: submit a complaint, retain the complaint ID, and track its progress.

The administrator experience should remain organized: review complaints, find relevant records, inspect details, and update statuses with appropriate accountability.

The initial release should implement these requirements reliably before expanding into optional features or additional integrations.

## Implementation Status

This status follows the original CloudPoint roadmap in Sections 1–17. Phase numbers keep their original objectives; implementation details and release gates are recorded separately below.

| Phase | Status | Current evidence and remaining work |
|---|---|---|
| 0 — Design decisions and acceptance boundaries | Documented | Initial roles, requirements, acceptance criteria, and exclusions are defined in this README. |
| 1 — Foundation and AWS environment preparation | Partial | WSGI, configuration, SQLite, DynamoDB/Lambda adapters, and unexecuted AWS templates/scripts are present. AWS service acceptance remains unverified. |
| 2 — Complaint submission and persistence | Implemented and tested locally | Validation, ID generation, persistence, and submission API pass the isolated Python API/foundation suite (88 Python tests overall). |
| 3 — Complaint tracking and privacy | Implemented and tested locally | ID tracking returns selected student-facing fields; API privacy and UI rendering checks pass locally. |
| 4 — Administrator authentication and authorization | Implemented in source | Scrypt credentials, signed/revocable sessions, expiry checks, and server-side authorization are present. Local account/database selection is environment-specific and must be verified. |
| 5 — Administrator complaint management | Implemented and tested locally | Listing, search, status/category filters, pagination, details, status updates, and rejection handling are covered by local API, DynamoDB-fake, and administrator UI tests. AWS behavior remains unverified. |
| 6 — Dashboard counts and operational visibility | Partial | Counts, request IDs, safe logs, alarms, and retention settings are implemented locally. AWS metrics, alarm actions, operator access, and cost remain unverified. |
| 7 — Quality, accessibility, and release readiness | Partial | Current local suites pass (88 Python, 9 administrator UI, 5 student UI checks). Previously documented Chrome evidence predates the latest narrow-screen student-header change; browser recheck, assistive-technology validation, backup/restore, and paired rollback remain open. |
| 8 — Future enhancements | Not started | No enhancement has been formally selected or approved. |

The local app uses Python's standard library, WSGI, and SQLite. `boto3` is optional for direct DynamoDB use. Admin credentials use salted scrypt hashes and revocable HMAC-signed bearer sessions. The deployment template uses a private S3 origin behind CloudFront HTTPS, API Gateway HTTP API v2, Lambda, DynamoDB, scoped runtime IAM, Secrets Manager, and CloudWatch. Deployment and cleanup scripts are guarded but unexecuted. No AWS resources have been provisioned or modified. Account eligibility, pricing, CloudFormation acceptance, deployed HTTPS behavior, effective IAM, and deployed workflows remain unverified. See [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md), [API_CONTRACTS.md](API_CONTRACTS.md), and `infra/cloudpoint.template.json`.

## 18. AWS Free-Tier-Conscious Implementation Plan

### 18.1 Deployment Objective and Cost Boundary

Deploy CloudPoint as a small serverless application without a continuously running server or a managed relational database. Target eligible AWS Free Tier allowances, but treat zero cost as a goal rather than a guarantee. Eligibility, included usage, service pricing, and account terms can change; verify them in the selected account and region before provisioning resources.

The plan below minimizes infrastructure while preserving the required student and administrator workflows. It does not waive security or transport requirements for public deployment.

### 18.2 Initial AWS Service Set

Use these services for the initial deployment:

- **Amazon S3** for static frontend files.
- **Amazon API Gateway HTTP API** for the application API.
- **AWS Lambda** for Python backend logic.
- **Amazon DynamoDB** for complaint records and optional status history.
- **AWS IAM** for service and deployment permissions.
- **Amazon CloudWatch** for essential application logs and operational metrics.
- **AWS Secrets Manager** for the administrator session signing key. This is an explicit security exception to the minimal core set: the key is generated and read at Lambda initialization, rather than passed through CloudFormation into Lambda environment variables. Include its current account and region pricing in the deployment review.

Use one AWS region. Keep Lambda outside a VPC unless a real network requirement arises; DynamoDB access does not require placing Lambda in a VPC. Do not provision EC2, a continuously running server, a managed relational database, or optional notification, search, analytics, and tracing services for the initial release.

### 18.3 Hosting and HTTPS Decision

S3 website endpoints do not provide HTTPS. Public submission and tracking transmit student information, so an HTTP-only public deployment is not acceptable. Before launch, select an HTTPS-capable hosting configuration and verify the complete browser-to-API path uses HTTPS.

The simplest S3 static website endpoint may be used only for local or controlled demonstrations where no real student information is entered and the HTTP limitation is explicitly disclosed. For a public demonstration or real use, the hosting design must add an HTTPS-capable front door (commonly CloudFront in front of a private S3 origin), or choose another suitable HTTPS-capable host. This is a justified exception to the minimal service list, not an optional enhancement. A custom domain and Route 53 are not required; the hosting provider's HTTPS endpoint can be used where available.

Keep S3 permissions limited to the chosen hosting configuration. Do not make the bucket broadly writable or expose stored deployment artifacts. Configure the frontend API base URL per environment and configure API CORS to the actual frontend origin; CORS is a browser control, not an authorization mechanism.

### 18.4 DynamoDB Data and Query Strategy

Design the table and indexes from the required access patterns before creating them. Complaint ID should support direct retrieval for student tracking and administrator detail lookup. Use backend-generated, sufficiently unpredictable identifiers; enforce uniqueness with a conditional write so a collision cannot overwrite an existing complaint.

The initial administrator interface needs listing, category/status filtering, ID search, title search, registration-number search, and dashboard counts. DynamoDB efficiently supports key-based queries, not arbitrary partial-text search across fields. Before implementation, specify whether title and registration-number search means exact, prefix, or limited partial matching. If the initial data volume is small, a paginated scan with server-side filtering may be acceptable for a prototype, but it reads records that do not match and can become slow or costly. Document a dataset/request threshold for that approach and revisit the index or storage design before it is exceeded. Do not claim scalable partial search without an index or search service that supports it.

Use pagination for complaint listings and scans; never assume a single DynamoDB response contains every matching record. Apply search and category/status filters consistently across pages. Dashboard counts may use a full paginated scan for a small dataset, with its read cost and latency documented. If counts must remain efficient at larger volume, introduce a carefully maintained aggregate or a queryable status index and define its consistency behavior; do not silently present stale or incomplete counts as exact. No separate analytics store is needed.

Store current complaint state and timestamps together so status changes are atomic. If status history is included, key it so history is queryable by complaint ID; append the history entry and update current state atomically where practical. History is a future enhancement in the existing scope, so it is optional for the first release unless auditability is made a requirement.

### 18.5 Authentication, Authorization, and Tracking Privacy

Choose administrator authentication before deployment. Do not store plaintext passwords, put credentials in frontend files, or authorize based on a role/administrator ID supplied by the browser. Every administrative API operation must verify a signed, unexpired authentication credential and the administrator's authorization on the server side. Login must resist brute-force attempts through suitable throttling and generic failure messages; logout must invalidate the session or credential according to the selected design.

A small prototype may use a well-supported password-hashing library and signed sessions/tokens, provided secrets are kept out of source control and frontend assets, token lifetime and revocation behavior are documented, and the prototype's operational limitations are stated. The deployment template stores the signing key in Secrets Manager and grants Lambda `GetSecretValue` only on that secret. A managed identity provider is an alternative, but verify current account eligibility, pricing, and integration requirements first. Do not improvise cryptography or build a custom password protocol.

Complaint-ID-only tracking makes the ID a bearer secret: anyone who obtains it can access whatever the endpoint returns. Return only the student-facing fields, avoid logging IDs and personal details, and decide whether an additional verification factor is required before showing names, registration numbers, or full descriptions. Use unpredictable IDs, rate limits, and throttling, while recognizing these do not replace an access policy. Separate public student routes from protected administrator routes.

### 18.6 Cost and Operational Controls

Before creating resources:

1. Verify active account eligibility, current free-tier allowances, and regional pricing.
2. Set a budget or billing alert where the account supports it; alerts do not cap spending.
3. Estimate request volume, Lambda duration, DynamoDB reads/writes, storage, logs, and data transfer.
4. Use small test datasets and validate query patterns before deployment.
5. Set short, suitable CloudWatch log retention and avoid logging credentials, tokens, complaint text, or unnecessary personal data.
6. Monitor API requests, Lambda errors/duration/throttles, DynamoDB consumption, storage, and transfer.
7. Avoid repeated polling, unbounded scans, and unnecessary retries; make write retries safe where possible.
8. Review billing after testing and remove unused resources.

Free-tier allowances do not ensure that every configuration is free. HTTPS hosting, data transfer, logging, request volume, and account eligibility can affect cost. Recheck pricing at deployment time rather than relying on historical limits.

### 18.7 Implementation Phases and Exit Criteria

This section uses the original roadmap objectives; it is not a separate phase sequence.

#### Phase 0 — Design decisions and acceptance boundaries

Confirm scope, design decisions, acceptance boundaries, and exclusions before implementation.

#### Phase 1 — Foundation and AWS environment preparation

Establish application configuration, the repository/database foundation, and deployment prerequisites. Prepare infrastructure definitions without treating them as deployed or service-validated.

#### Phase 2 — Complaint submission and persistence

Implement validation, unique complaint IDs, persistence, and submission endpoints. Accept only after the isolated local submission/persistence workflow passes.

#### Phase 3 — Complaint tracking and privacy

Implement tracking by complaint ID and enforce the intended privacy boundary for student responses.

#### Phase 4 — Administrator authentication and authorization

Implement administrator login/logout, session handling, and protection of every administrator endpoint.

#### Phase 5 — Administrator complaint management

Implement listing, search, filtering, pagination, details, status updates, rejection reasons, and the required administrator workflows.

#### Phase 6 — Dashboard counts and operational visibility

Implement dashboard counts, consistent counting methods, request correlation IDs, safe structured logs, CloudWatch alarms, retention considerations, and operational investigation support.

#### Phase 7 — Quality, accessibility, and release readiness

Evaluate end-to-end behavior, regression coverage, responsive layouts, accessibility, operational limitations, backup/recovery, rollback, and release readiness. Local checks do not establish AWS service acceptance or deployed behavior.

#### Phase 8 — Future enhancements

Evaluate future enhancements only after the original workflows are stable. No candidate enhancement is selected or approved by this document.

### 18.8 Explicitly Deferred Infrastructure

Defer custom domains and Route 53, WAF, VPC/NAT, multiple environments, dedicated search, separate analytics databases, relational databases, notifications, file uploads, multi-region replication, elaborate CI/CD, advanced dashboards, distributed tracing, and advanced disaster recovery unless a specific requirement justifies them. CloudFront is also deferred by default only for non-public/controlled demonstrations; use an HTTPS-capable front door for public use as described in Section 18.3.

### 18.9 Deployment Definition of Done

The initial AWS deployment is complete when the frontend loads through the appropriate hosting configuration; students can submit and track current status; complaints persist in DynamoDB; administrators authenticate and can list, search, filter, inspect, and update records; rejection reasons and timestamps are correct; counts follow documented rules; unauthorized admin requests fail; no continuously running server is required; essential end-to-end scenarios pass; account eligibility and cost have been reviewed; and deployment, configuration, testing, and cleanup are documented.
