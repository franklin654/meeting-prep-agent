export interface paths {
    "/api/meetings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Meetings
         * @description Meetings with attendees and brief status, soonest first.
         */
        get: operations["list_meetings_api_meetings_get"];
        put?: never;
        /** Schedule Meeting */
        post: operations["schedule_meeting_api_meetings_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/meetings/{meeting_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Delete Meeting */
        delete: operations["delete_meeting_api_meetings__meeting_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/meetings/{meeting_id}/prepared": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Prepare Meeting */
        post: operations["prepare_meeting_api_meetings__meeting_id__prepared_post"];
        /** Unprepare Meeting */
        delete: operations["unprepare_meeting_api_meetings__meeting_id__prepared_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/meetings/{meeting_id}/notes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit Notes
         * @description Save the transcript, create an ingest job and run ingest after the response.
         *
         *     The background task gets `session_factory`, not the request session, which is
         *     closed when the request ends. The meeting is marked done by ingest itself.
         */
        post: operations["submit_notes_api_meetings__meeting_id__notes_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/meetings/{meeting_id}/capture/preview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Preview Capture */
        post: operations["preview_capture_api_meetings__meeting_id__capture_preview_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/capture/{draft_id}/save": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Save Capture */
        post: operations["save_capture_api_capture__draft_id__save_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/capture/{draft_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Delete Capture */
        delete: operations["delete_capture_api_capture__draft_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/accounts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Accounts */
        get: operations["get_accounts_api_accounts_get"];
        put?: never;
        /** Post Account */
        post: operations["post_account_api_accounts_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/contacts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Contacts */
        get: operations["get_contacts_api_contacts_get"];
        put?: never;
        /** Post Contact */
        post: operations["post_contact_api_contacts_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/meetings/{meeting_id}/suggested-questions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Suggested Questions */
        get: operations["get_suggested_questions_api_meetings__meeting_id__suggested_questions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/ask": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Post Ask */
        post: operations["post_ask_api_ask_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/ask/{ask_answer_id}/pin": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Post Pin */
        post: operations["post_pin_api_ask__ask_answer_id__pin_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/memories/notes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Post Note */
        post: operations["post_note_api_memories_notes_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Job
         * @description `pending`, `done` (with the learned summary) or `failed` (with the error code).
         */
        get: operations["get_job_api_jobs__job_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/meetings/{meeting_id}/brief": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Read Brief
         * @description The stored brief; 404 when none exists or a later ingest made it stale.
         */
        get: operations["read_brief_api_meetings__meeting_id__brief_get"];
        put?: never;
        /**
         * Create Brief
         * @description Generate a fresh brief for the meeting, replacing any stored one for this mode.
         */
        post: operations["create_brief_api_meetings__meeting_id__brief_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/briefs/{brief_id}/feedback": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Post Feedback
         * @description Store the feedback row, retain one preference sentence, return the new profile.
         */
        post: operations["post_feedback_api_briefs__brief_id__feedback_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/style": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Style
         * @description The style profile derived from every feedback row.
         */
        get: operations["get_style_api_style_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/style/reset": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Reset Style
         * @description Clear all app feedback rows and return the default style profile.
         */
        post: operations["reset_style_api_style_reset_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/style/rules/{section}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Delete Style Rule
         * @description Remove the feedback history for one section and return the updated style profile.
         */
        delete: operations["delete_style_rule_api_style_rules__section__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/contacts/{contact_id}/timeline": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Contact Timeline
         * @description Everything memory knows about a contact, newest meeting first, deduplicated, max 30.
         */
        get: operations["contact_timeline_api_contacts__contact_id__timeline_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/contacts/{contact_id}/profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Contact Profile */
        get: operations["contact_profile_api_contacts__contact_id__profile_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/contacts/{contact_id}/patterns/refresh": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Refresh Patterns */
        post: operations["refresh_patterns_api_contacts__contact_id__patterns_refresh_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/memories/{memory_id}/hide": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Hide Memory */
        post: operations["hide_memory_api_memories__memory_id__hide_post"];
        /** Unhide Memory */
        delete: operations["unhide_memory_api_memories__memory_id__hide_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/memories/{memory_id}/correct": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Correct Memory */
        post: operations["correct_memory_api_memories__memory_id__correct_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/commitments/{commitment_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Remove Commitment */
        delete: operations["remove_commitment_api_commitments__commitment_id__delete"];
        options?: never;
        head?: never;
        /** Patch Commitment */
        patch: operations["patch_commitment_api_commitments__commitment_id__patch"];
        trace?: never;
    };
    "/api/nudges": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Nudges */
        get: operations["list_nudges_api_nudges_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health
         * @description Liveness stub.
         *
         *     Full dependency checks (Hindsight, DB) land with the memory and db gateways
         *     (T06, T07); for now this only proves the API process is up.
         */
        get: operations["health_api_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AccountCreate */
        AccountCreate: {
            /** Name */
            name: string;
            /** Industry */
            industry?: string | null;
            /**
             * Stage
             * @default discovery
             * @enum {string}
             */
            stage: "discovery" | "evaluation" | "closed_won" | "closed_lost";
        };
        /** AccountResponse */
        AccountResponse: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Industry */
            industry: string;
            /**
             * Stage
             * @enum {string}
             */
            stage: "discovery" | "evaluation" | "closed_won" | "closed_lost";
        };
        /** AskRequest */
        AskRequest: {
            /** Question */
            question: string;
            scope_type: components["schemas"]["ScopeType"];
            /** Scope Id */
            scope_id: string;
            /** History */
            history?: components["schemas"]["AskTurn"][];
        };
        /** AskResponse */
        AskResponse: {
            /** Ask Answer Id */
            ask_answer_id: string;
            /** Answer */
            answer: string;
            /** Grounded */
            grounded: boolean;
            /** Citations */
            citations: components["schemas"]["Citation"][];
        };
        /** AskTurn */
        AskTurn: {
            /** Question */
            question: string;
            /** Answer */
            answer: string;
        };
        /** Brief */
        Brief: {
            /** Id */
            id: string;
            /** Meeting Id */
            meeting_id: string;
            /**
             * Mode
             * @enum {string}
             */
            mode: "memory" | "no_memory";
            /**
             * Generated At
             * Format: date-time
             */
            generated_at: string;
            /** Sections */
            sections: components["schemas"]["BriefSection"][];
            /** Facts Used */
            facts_used: number;
            /** Preferences Applied */
            preferences_applied: string[];
            /**
             * You Owe
             * @default []
             */
            you_owe: components["schemas"]["OwedItem"][];
            /**
             * They Owe
             * @default []
             */
            they_owe: components["schemas"]["OwedItem"][];
            /**
             * Objections
             * @default []
             */
            objections: components["schemas"]["RankedObjection"][];
            /**
             * Memory Used
             * @default {
             *       "facts": 0,
             *       "meetings": 0
             *     }
             */
            memory_used: {
                [key: string]: number;
            };
            /**
             * Contact Cards
             * @default []
             */
            contact_cards: components["schemas"]["ContactCard"][];
            /**
             * First Meeting
             * @default false
             */
            first_meeting: boolean;
        };
        /** BriefItem */
        BriefItem: {
            /** Id */
            id: string;
            /** Text */
            text: string;
            severity: components["schemas"]["Severity"];
            /** Contact Ids */
            contact_ids: string[];
            /** Citations */
            citations: components["schemas"]["Citation"][];
        };
        /** BriefSection */
        BriefSection: {
            key: components["schemas"]["SectionKey"];
            /** Title */
            title: string;
            /** Items */
            items: components["schemas"]["BriefItem"][];
            /**
             * Collapsed
             * @default false
             */
            collapsed: boolean;
        };
        /** CaptureDraftResponse */
        CaptureDraftResponse: {
            /** Draft Id */
            draft_id: string;
            /** Meeting Id */
            meeting_id: string;
            /** Items */
            items: components["schemas"]["CaptureItem"][];
            /** Counts */
            counts: {
                [key: string]: number;
            };
        };
        /** CaptureItem */
        CaptureItem: {
            /** Id */
            id: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "commitment" | "closes" | "fact";
            fact_kind?: components["schemas"]["FactKind"] | null;
            /** Text */
            text: string;
            /** Owner */
            owner?: string | null;
            /** Contact */
            contact?: string | null;
            /** Due Date */
            due_date?: string | null;
            /** Quote */
            quote: string;
            /**
             * Badge
             * @enum {string}
             */
            badge: "new" | "closes" | "duplicate" | "updates_due_date";
            /** Target Commitment Id */
            target_commitment_id?: string | null;
            /**
             * Checked
             * @default true
             */
            checked: boolean;
        };
        /** CapturePreviewRequest */
        CapturePreviewRequest: {
            /** Transcript */
            transcript: string;
        };
        /** CaptureSaveRequest */
        CaptureSaveRequest: {
            /** Unchecked Item Ids */
            unchecked_item_ids?: string[];
        };
        /** Citation */
        Citation: {
            source_type: components["schemas"]["SourceType"];
            /** Meeting Id */
            meeting_id: string | null;
            /** Meeting Date */
            meeting_date: string | null;
            /** Label */
            label: string;
            /** Quote */
            quote: string | null;
            /** Memory Id */
            memory_id: string | null;
        };
        /** CommitmentPatch */
        CommitmentPatch: {
            status?: components["schemas"]["CommitmentStatus"] | null;
            /** Due Date */
            due_date?: string | null;
            /** Text */
            text?: string | null;
        };
        /** CommitmentResponse */
        CommitmentResponse: {
            /** Id */
            id: string;
            owner: components["schemas"]["Owner"];
            /** Text */
            text: string;
            /** Due Date */
            due_date: string | null;
            status: components["schemas"]["CommitmentStatus"];
            citation: components["schemas"]["Citation"];
            /** Meeting Id */
            meeting_id: string;
        };
        /**
         * CommitmentStatus
         * @enum {string}
         */
        CommitmentStatus: "open" | "done";
        /** ContactCard */
        ContactCard: {
            /** Contact Id */
            contact_id: string;
            /** Name */
            name: string;
            /** Role */
            role: string | null;
            /** Account */
            account: string;
            /** Style */
            style?: string | null;
            /**
             * Style Citations
             * @default []
             */
            style_citations: components["schemas"]["Citation"][];
            /**
             * Recent Meetings
             * @default []
             */
            recent_meetings: components["schemas"]["Citation"][];
            /**
             * Open Follow Ups
             * @default 0
             */
            open_follow_ups: number;
        };
        /** ContactCreate */
        ContactCreate: {
            /** Account Id */
            account_id: string;
            /** Name */
            name: string;
            /** Role */
            role?: string | null;
            /** Aliases */
            aliases?: string[];
        };
        /** ContactMeetingTimeline */
        ContactMeetingTimeline: {
            /** Meeting Id */
            meeting_id: string;
            /** Title */
            title: string;
            /**
             * Meeting Date
             * Format: date
             */
            meeting_date: string;
            /** Items */
            items: components["schemas"]["ProfileTimelineItem"][];
        };
        /** ContactPattern */
        ContactPattern: {
            /** Text */
            text: string;
            /** Fact Ids */
            fact_ids: string[];
            /** Citations */
            citations: components["schemas"]["Citation"][];
        };
        /** ContactProfile */
        ContactProfile: {
            contact: components["schemas"]["ContactRef"];
            account: components["schemas"]["AccountResponse"];
            stats: components["schemas"]["ContactProfileStats"];
            /** Timeline */
            timeline: components["schemas"]["ContactMeetingTimeline"][];
            /** Facts */
            facts: components["schemas"]["ProfileFact"][];
            /** Follow Ups */
            follow_ups: components["schemas"]["ProfileCommitment"][];
            /** Preferences */
            preferences: components["schemas"]["ProfileFact"][];
            /** Patterns */
            patterns: components["schemas"]["ContactPattern"][];
            /** Hidden Count */
            hidden_count: number;
        };
        /** ContactProfileStats */
        ContactProfileStats: {
            /** Meetings */
            meetings: number;
            /** Facts */
            facts: number;
            /** Open Follow Ups */
            open_follow_ups: number;
        };
        /** ContactRef */
        ContactRef: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Role */
            role: string | null;
        };
        /** ContactSummary */
        ContactSummary: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Role */
            role: string | null;
            /** Account Id */
            account_id: string | null;
            /** Account Name */
            account_name: string | null;
            /**
             * Meetings Count
             * @default 0
             */
            meetings_count: number;
            /**
             * Open Followups
             * @default 0
             */
            open_followups: number;
            /** Last Meeting Date */
            last_meeting_date?: string | null;
        };
        /** ContactTimeline */
        ContactTimeline: {
            contact: components["schemas"]["ContactRef"];
            /** Entries */
            entries: components["schemas"]["TimelineEntry"][];
        };
        /**
         * FactKind
         * @enum {string}
         */
        FactKind: "commitment" | "objection" | "personal" | "deal_fact" | "competitor";
        /** FeedbackRequest */
        FeedbackRequest: {
            section: components["schemas"]["SectionKey"];
            /**
             * Action
             * @enum {string}
             */
            action: "up" | "down" | "more" | "less" | "collapsed";
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** JobAccepted */
        JobAccepted: {
            /** Job Id */
            job_id: string;
        };
        /** JobStatus */
        JobStatus: {
            /** Id */
            id: string;
            /** Kind */
            kind: string;
            /**
             * Status
             * @enum {string}
             */
            status: "pending" | "done" | "failed";
            learned?: components["schemas"]["LearnedSummary"] | null;
            draft?: components["schemas"]["CaptureDraftResponse"] | null;
            /** Error */
            error?: string | null;
        };
        /** LearnedSummary */
        LearnedSummary: {
            /** Facts */
            facts: string[];
            /** New Commitments */
            new_commitments: number;
            /** Closed Commitments */
            closed_commitments: number;
            /** Alerts */
            alerts: string[];
        };
        /** MeetingCreate */
        MeetingCreate: {
            /** Account Id */
            account_id: string;
            /** Title */
            title: string;
            /**
             * Scheduled At
             * Format: date-time
             */
            scheduled_at: string;
            /** Attendee Ids */
            attendee_ids?: string[];
        };
        /** MeetingSummary */
        MeetingSummary: {
            /** Id */
            id: string;
            /** Account Id */
            account_id: string;
            /** Account Name */
            account_name: string;
            /** Title */
            title: string;
            /**
             * Scheduled At
             * Format: date-time
             */
            scheduled_at: string;
            /** Status */
            status: string;
            /** Attendees */
            attendees: components["schemas"]["ContactRef"][];
            /** Brief Ready */
            brief_ready: boolean;
            /**
             * Prepared
             * @default false
             */
            prepared: boolean;
            /**
             * Open Followups
             * @default 0
             */
            open_followups: number;
            /**
             * Past Meetings
             * @default 0
             */
            past_meetings: number;
            /**
             * Has History
             * @default false
             */
            has_history: boolean;
        };
        /** MemoryCorrectionRequest */
        MemoryCorrectionRequest: {
            /** Corrected Text */
            corrected_text: string;
            scope_type?: components["schemas"]["ScopeType"] | null;
            /** Scope Id */
            scope_id?: string | null;
        };
        /** NoteRequest */
        NoteRequest: {
            /** Text */
            text: string;
            scope_type: components["schemas"]["ScopeType"];
            /** Scope Id */
            scope_id: string;
        };
        /** NotesRequest */
        NotesRequest: {
            /** Transcript */
            transcript: string;
        };
        /** Nudge */
        Nudge: {
            /**
             * Kind
             * @enum {string}
             */
            kind: "overdue_commitment" | "they_owe_overdue" | "no_history" | "silent_contact" | "brief_ready";
            /** Text */
            text: string;
            /** Link */
            link: string;
        };
        /** OwedItem */
        OwedItem: {
            /** Text */
            text: string;
            /** Due Date */
            due_date: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "open" | "overdue";
            /** Days Overdue */
            days_overdue: number;
            /** Owner Name */
            owner_name: string;
            severity: components["schemas"]["Severity"];
            /** Citations */
            citations: components["schemas"]["Citation"][];
        };
        /**
         * Owner
         * @enum {string}
         */
        Owner: "us" | "them";
        /** PinRequest */
        PinRequest: {
            /** Meeting Id */
            meeting_id: string;
        };
        /** ProfileCommitment */
        ProfileCommitment: {
            /** Id */
            id: string;
            owner: components["schemas"]["Owner"];
            /** Text */
            text: string;
            /** Due Date */
            due_date: string | null;
            status: components["schemas"]["CommitmentStatus"];
            citation: components["schemas"]["Citation"];
        };
        /** ProfileFact */
        ProfileFact: {
            /** Id */
            id: string;
            kind: components["schemas"]["FactKind"];
            /** Text */
            text: string;
            /**
             * Learned On
             * Format: date
             */
            learned_on: string;
            citation: components["schemas"]["Citation"];
        };
        /** ProfileTimelineItem */
        ProfileTimelineItem: {
            /** Kind */
            kind: string;
            /** Text */
            text: string;
            /**
             * Learned On
             * Format: date
             */
            learned_on: string;
            citation: components["schemas"]["Citation"];
        };
        /** RankedObjection */
        RankedObjection: {
            /** Topic */
            topic: string;
            /** Count */
            count: number;
            /** Dates */
            dates: string[];
            /** Citations */
            citations: components["schemas"]["Citation"][];
        };
        /**
         * ScopeType
         * @enum {string}
         */
        ScopeType: "account" | "contact" | "meeting";
        /**
         * SectionKey
         * @enum {string}
         */
        SectionKey: "attendees" | "where_left_off" | "open_commitments" | "unresolved_objections" | "personal_touchpoints" | "agenda" | "watch_outs" | "alerts" | "your_questions";
        /**
         * Severity
         * @enum {string}
         */
        Severity: "info" | "warning" | "critical";
        /**
         * SourceType
         * @enum {string}
         */
        SourceType: "meeting" | "ledger" | "mental_model" | "ask";
        /** StyleProfile */
        StyleProfile: {
            /** Section Order */
            section_order: components["schemas"]["SectionKey"][];
            /** Hidden Sections */
            hidden_sections: components["schemas"]["SectionKey"][];
            /**
             * Length
             * @enum {string}
             */
            length: "short" | "standard" | "detailed";
            /** Notes */
            notes: string[];
        };
        /** SuggestedQuestions */
        SuggestedQuestions: {
            /** Questions */
            questions: string[];
        };
        /** TimelineEntry */
        TimelineEntry: {
            /** Text */
            text: string;
            fact_kind: components["schemas"]["FactKind"] | null;
            /**
             * Learned On
             * Format: date
             */
            learned_on: string;
            citation: components["schemas"]["Citation"];
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    list_meetings_api_meetings_get: {
        parameters: {
            query?: {
                status?: ("upcoming" | "done") | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MeetingSummary"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    schedule_meeting_api_meetings_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MeetingCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MeetingSummary"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_meeting_api_meetings__meeting_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                meeting_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    prepare_meeting_api_meetings__meeting_id__prepared_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                meeting_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    unprepare_meeting_api_meetings__meeting_id__prepared_delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                meeting_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    submit_notes_api_meetings__meeting_id__notes_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                meeting_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NotesRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobAccepted"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    preview_capture_api_meetings__meeting_id__capture_preview_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                meeting_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CapturePreviewRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobAccepted"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    save_capture_api_capture__draft_id__save_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                draft_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CaptureSaveRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobAccepted"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_capture_api_capture__draft_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                draft_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_accounts_api_accounts_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AccountResponse"][];
                };
            };
        };
    };
    post_account_api_accounts_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AccountCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AccountResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_contacts_api_contacts_get: {
        parameters: {
            query?: {
                query?: string | null;
                account_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContactSummary"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    post_contact_api_contacts_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ContactCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContactSummary"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_suggested_questions_api_meetings__meeting_id__suggested_questions_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                meeting_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SuggestedQuestions"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    post_ask_api_ask_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AskRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AskResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    post_pin_api_ask__ask_answer_id__pin_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                ask_answer_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PinRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AskResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    post_note_api_memories_notes_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NoteRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobAccepted"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_job_api_jobs__job_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobStatus"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    read_brief_api_meetings__meeting_id__brief_get: {
        parameters: {
            query?: {
                mode?: "memory" | "no_memory";
            };
            header?: never;
            path: {
                meeting_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Brief"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_brief_api_meetings__meeting_id__brief_post: {
        parameters: {
            query?: {
                mode?: "memory" | "no_memory";
            };
            header?: never;
            path: {
                meeting_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Brief"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    post_feedback_api_briefs__brief_id__feedback_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                brief_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FeedbackRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StyleProfile"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_style_api_style_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StyleProfile"];
                };
            };
        };
    };
    reset_style_api_style_reset_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StyleProfile"];
                };
            };
        };
    };
    delete_style_rule_api_style_rules__section__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                section: components["schemas"]["SectionKey"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StyleProfile"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    contact_timeline_api_contacts__contact_id__timeline_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                contact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContactTimeline"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    contact_profile_api_contacts__contact_id__profile_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                contact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContactProfile"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    refresh_patterns_api_contacts__contact_id__patterns_refresh_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                contact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContactPattern"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    hide_memory_api_memories__memory_id__hide_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                memory_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    unhide_memory_api_memories__memory_id__hide_delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                memory_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    correct_memory_api_memories__memory_id__correct_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                memory_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MemoryCorrectionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobAccepted"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    remove_commitment_api_commitments__commitment_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                commitment_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    patch_commitment_api_commitments__commitment_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                commitment_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CommitmentPatch"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CommitmentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_nudges_api_nudges_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Nudge"][];
                };
            };
        };
    };
    health_api_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
}
